from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath

import apsw

from ..config import AppPaths
from ..storage.database import StorageError, require_row, transaction, utc_now
from ..storage.files import FileRepository
from ..storage.repositories import PaperDraft, PaperRepository, normalize_title
from .analysis import PdfAnalysisError, inspect_pdf

MAX_PDF_BYTES = 250 * 1024 * 1024


class PdfUploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedPdf:
    token: str
    original_name: str
    sha256: str
    size_bytes: int
    page_count: int
    preview: dict[str, object]


class PdfIngestService:
    def __init__(
        self,
        connection: apsw.Connection,
        paths: AppPaths,
        inspector: object | None = None,
    ) -> None:
        self.connection = connection
        self.paths = paths
        self.inspector = inspector

    def temporary_path(self, token: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            raise PdfUploadError("无效的上传会话")
        root = (self.paths.runtime / "uploads").resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = (root / f"{token}.part").resolve()
        if not target.is_relative_to(root):
            raise PdfUploadError("上传路径越界")
        return target

    def preview_staged(
        self,
        *,
        token: str,
        filename: str,
        sha256: str,
        size_bytes: int,
        paper_id: int | None,
    ) -> StagedPdf:
        path = self.temporary_path(token)
        if not path.is_file() or path.stat().st_size != size_bytes:
            raise PdfUploadError("临时上传文件不完整")
        with path.open("rb") as source:
            header = source.read(1_024)
        if b"%PDF-" not in header:
            path.unlink(missing_ok=True)
            raise PdfUploadError("上传内容不是 PDF 文件")
        try:
            if self.inspector is None:
                page_count, candidates = inspect_pdf(path)
            else:
                page_count, candidates = self.inspector.inspect(path)  # type: ignore[attr-defined]
        except PdfAnalysisError:
            path.unlink(missing_ok=True)
            raise
        except RuntimeError as error:
            path.unlink(missing_ok=True)
            raise PdfAnalysisError(str(error)) from error
        preview = self._duplicates(sha256, candidates, paper_id)
        preview["candidates"] = candidates
        expires = datetime.now(UTC) + timedelta(hours=24)
        safe_name = PurePath(filename).name[:240] or "document.pdf"
        self.connection.execute(
            """
            INSERT INTO pdf_upload_sessions(
                token, temporary_path, original_name, sha256, size_bytes,
                page_count, preview_json, created_at, expires_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                path.name,
                safe_name,
                sha256,
                size_bytes,
                page_count,
                json.dumps(preview, ensure_ascii=False),
                utc_now(),
                expires.isoformat(),
            ),
        )
        return StagedPdf(token, safe_name, sha256, size_bytes, page_count, preview)

    def confirm(
        self,
        *,
        token: str,
        paper_id: int | None,
        resolution: str,
        matched_paper_id: int | None = None,
    ) -> tuple[int, int, Path, bool]:
        row = self.connection.execute(
            """
            SELECT temporary_path, original_name, sha256, size_bytes,
                   page_count, preview_json, expires_at
            FROM pdf_upload_sessions WHERE token=?
            """,
            (token,),
        ).fetchone()
        if row is None:
            raise PdfUploadError("上传会话不存在或已经处理")
        temporary = self.temporary_path(token)
        preview = json.loads(str(row[5]))
        if datetime.fromisoformat(str(row[6])) <= datetime.now(UTC):
            self.cancel(token)
            raise PdfUploadError("上传会话已过期, 请重新选择 PDF")
        if resolution == "cancel":
            self.cancel(token)
            raise PdfUploadError("上传已取消")
        if resolution not in {"attach", "link_existing", "keep_version"}:
            raise PdfUploadError("请选择重复文件的处理方式")
        duplicate_level = str(preview.get("duplicate_level", "none"))
        if duplicate_level != "none" and resolution == "attach":
            raise PdfUploadError("检测到重复, 必须明确选择关联或保留版本")
        target_paper = paper_id
        if resolution == "link_existing" and matched_paper_id is not None:
            target_paper = matched_paper_id
        if target_paper is None:
            target_paper = self._create_paper(preview)
        digest = str(row[2])
        existing = self.connection.execute(
            "SELECT id FROM files WHERE sha256=?", (digest,)
        ).fetchone()
        deduplicated = existing is not None
        if existing is not None:
            file_id = int(existing[0])
            temporary.unlink(missing_ok=True)
        else:
            target = (self.paths.library / "pdfs" / digest[:2] / f"{digest}.pdf").resolve()
            library_root = self.paths.library.resolve()
            if not target.is_relative_to(library_root):
                raise StorageError("PDF target path is outside the local library")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, target)
            relative = target.relative_to(library_root).as_posix()
            file_id = FileRepository(self.connection, library_root).register(
                sha256=digest,
                relative_path=relative,
                original_name=str(row[1]),
                size_bytes=int(row[3]),
                page_count=int(row[4]),
            )
        target = self.path_for_file(file_id)
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO paper_files(paper_id, file_id, version_role, created_at)
                VALUES(?, ?, ?, ?) ON CONFLICT(paper_id, file_id) DO NOTHING
                """,
                (
                    target_paper,
                    file_id,
                    "alternate" if resolution == "keep_version" else "primary",
                    utc_now(),
                ),
            )
            self.connection.execute("DELETE FROM pdf_upload_sessions WHERE token=?", (token,))
        return target_paper, file_id, target, deduplicated

    def cancel(self, token: str) -> None:
        self.temporary_path(token).unlink(missing_ok=True)
        self.connection.execute("DELETE FROM pdf_upload_sessions WHERE token=?", (token,))

    def cleanup_expired(self) -> int:
        now = datetime.now(UTC)
        tokens = [
            str(row[0])
            for row in self.connection.execute("SELECT token, expires_at FROM pdf_upload_sessions")
            if datetime.fromisoformat(str(row[1])) <= now
        ]
        for token in tokens:
            self.cancel(token)
        upload_root = self.paths.runtime / "uploads"
        known = {
            f"{row[0]}.part"
            for row in self.connection.execute("SELECT token FROM pdf_upload_sessions")
        }
        if upload_root.exists():
            for part in upload_root.glob("*.part"):
                if part.name not in known:
                    part.unlink(missing_ok=True)
        return len(tokens)

    def path_for_file(self, file_id: int) -> Path:
        row = require_row(
            self.connection.execute(
                "SELECT relative_path FROM files WHERE id=?", (file_id,)
            ).fetchone(),
            "locating PDF",
        )
        root = self.paths.library.resolve()
        path = (root / str(row[0])).resolve()
        if not path.is_relative_to(root):
            raise StorageError("Stored PDF path is outside the local library")
        return path

    def _duplicates(
        self, sha256: str, candidates: list[dict[str, object]], paper_id: int | None
    ) -> dict[str, object]:
        exact = self.connection.execute(
            "SELECT id, original_name FROM files WHERE sha256=?", (sha256,)
        ).fetchone()
        if exact is not None:
            return {
                "duplicate_level": "exact",
                "matches": [{"file_id": int(exact[0]), "name": exact[1]}],
                "paper_id": paper_id,
            }
        values = {str(item["field_name"]): str(item["value"]) for item in candidates}
        doi = values.get("doi")
        if doi:
            rows = self.connection.execute(
                """
                SELECT p.id, p.title_original FROM papers p
                WHERE lower(p.doi)=lower(?) AND (
                    p.id<>? OR EXISTS(SELECT 1 FROM paper_files pf WHERE pf.paper_id=p.id)
                )
                """,
                (doi, paper_id or -1),
            ).fetchall()
            if rows:
                return {
                    "duplicate_level": "doi",
                    "matches": [
                        {"paper_id": int(str(row[0])), "title": row[1]} for row in rows
                    ],
                    "paper_id": paper_id,
                }
        title = values.get("title")
        year = values.get("year")
        if title:
            normalized = normalize_title(title)
            matches: list[dict[str, object]] = []
            for row in self.connection.execute(
                "SELECT id, title_original, publication_year FROM papers"
            ):
                if int(str(row[0])) == paper_id:
                    has_file = self.connection.execute(
                        "SELECT 1 FROM paper_files WHERE paper_id=? LIMIT 1", (paper_id,)
                    ).fetchone()
                    if has_file is None:
                        continue
                if normalize_title(str(row[1])) == normalized and (
                    not year or row[2] is None or str(row[2]) == year
                ):
                    matches.append(
                        {"paper_id": int(str(row[0])), "title": row[1], "year": row[2]}
                    )
            if matches:
                return {"duplicate_level": "weak", "matches": matches, "paper_id": paper_id}
        return {"duplicate_level": "none", "matches": [], "paper_id": paper_id}

    def _create_paper(self, preview: dict[str, object]) -> int:
        candidate_source = preview.get("candidates", [])
        candidates = candidate_source if isinstance(candidate_source, list) else []
        values = {
            str(item["field_name"]): str(item["value"])
            for item in candidates
            if isinstance(item, dict)
        }
        title = values.get("title", "未命名 PDF 文献")
        year = int(values["year"]) if values.get("year", "").isdigit() else None
        return PaperRepository(self.connection).create(
            PaperDraft(title, doi=values.get("doi"), year=year)
        )


def new_upload_token() -> str:
    return uuid.uuid4().hex
