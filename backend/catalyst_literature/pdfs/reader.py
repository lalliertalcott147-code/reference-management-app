from __future__ import annotations

import json
from dataclasses import dataclass

import apsw

from ..library import LibraryService
from ..storage.database import require_row, transaction, utc_now


@dataclass(frozen=True)
class ReadingPosition:
    file_id: int
    paper_id: int
    page_number: int
    scale: float
    scroll_offset: float


class PdfReaderService:
    def __init__(self, connection: apsw.Connection, library: LibraryService) -> None:
        self.connection = connection
        self.library = library

    def ensure_link(self, file_id: int, paper_id: int) -> None:
        row = self.connection.execute(
            "SELECT 1 FROM paper_files WHERE file_id=? AND paper_id=?", (file_id, paper_id)
        ).fetchone()
        if row is None:
            raise ValueError("PDF is not linked to this paper")

    def get_position(self, file_id: int, paper_id: int) -> ReadingPosition:
        self.ensure_link(file_id, paper_id)
        row = self.connection.execute(
            """
            SELECT page_number, scale, scroll_offset FROM pdf_reading_positions
            WHERE file_id=? AND paper_id=?
            """,
            (file_id, paper_id),
        ).fetchone()
        if row is None:
            return ReadingPosition(file_id, paper_id, 1, 1.0, 0.0)
        return ReadingPosition(file_id, paper_id, int(row[0]), float(row[1]), float(row[2]))

    def save_position(
        self,
        file_id: int,
        paper_id: int,
        page_number: int,
        scale: float,
        scroll_offset: float,
    ) -> None:
        self.ensure_link(file_id, paper_id)
        page_count = require_row(
            self.connection.execute(
                "SELECT page_count FROM files WHERE id=?", (file_id,)
            ).fetchone(),
            "reading PDF page count",
        )[0]
        safe_page = min(max(1, page_number), max(1, int(str(page_count))))
        self.connection.execute(
            """
            INSERT INTO pdf_reading_positions(
                file_id, paper_id, page_number, scale, scroll_offset, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id, paper_id) DO UPDATE SET
                page_number=excluded.page_number, scale=excluded.scale,
                scroll_offset=excluded.scroll_offset, updated_at=excluded.updated_at
            """,
            (file_id, paper_id, safe_page, scale, scroll_offset, utc_now()),
        )

    def list_annotations(
        self,
        file_id: int,
        paper_id: int,
        *,
        annotation_type: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, object]]:
        self.ensure_link(file_id, paper_id)
        file_hash = str(
            require_row(
                self.connection.execute(
                    "SELECT sha256 FROM files WHERE id=?", (file_id,)
                ).fetchone(),
                "reading PDF hash",
            )[0]
        )
        self.connection.execute(
            "UPDATE pdf_annotations SET is_stale=(file_sha256<>?) WHERE file_id=?",
            (file_hash, file_id),
        )
        clauses = ["file_id=?", "paper_id=?"]
        parameters: list[int | str] = [file_id, paper_id]
        if annotation_type:
            clauses.append("annotation_type=?")
            parameters.append(annotation_type)
        if query:
            clauses.append("(selected_text LIKE ? OR comment_text LIKE ?)")
            pattern = f"%{query}%"
            parameters.extend((pattern, pattern))
        return [
            {
                "id": int(row[0]),
                "note_id": row[1],
                "annotation_type": row[2],
                "page_number": int(row[3]),
                "color": row[4],
                "selected_text": row[5],
                "prefix_text": row[6],
                "suffix_text": row[7],
                "rects": json.loads(str(row[8])),
                "comment_text": row[9],
                "is_stale": bool(row[10]),
                "updated_at": row[11],
            }
            for row in self.connection.execute(
                f"""
                SELECT id, note_id, annotation_type, page_number, color,
                       selected_text, prefix_text, suffix_text, rects_json,
                       comment_text, is_stale, updated_at
                FROM pdf_annotations WHERE {' AND '.join(clauses)}
                ORDER BY page_number, id
                """,
                parameters,
            )
        ]

    def create_annotation(
        self,
        file_id: int,
        paper_id: int,
        *,
        annotation_type: str,
        page_number: int,
        color: str,
        selected_text: str,
        prefix_text: str,
        suffix_text: str,
        rects: list[dict[str, float]],
        comment_text: str,
    ) -> int:
        self.ensure_link(file_id, paper_id)
        file_hash = str(
            require_row(
                self.connection.execute(
                    "SELECT sha256 FROM files WHERE id=?", (file_id,)
                ).fetchone(),
                "reading annotation hash",
            )[0]
        )
        note_body = self._note_body(
            annotation_type, page_number, selected_text, comment_text, file_id
        )
        note_id, _version = self.library.save_note(paper_id, note_body)
        try:
            now = utc_now()
            self.connection.execute(
                """
                INSERT INTO pdf_annotations(
                    file_id, paper_id, note_id, annotation_type, page_number, color,
                    selected_text, prefix_text, suffix_text, rects_json, comment_text,
                    created_at, updated_at, file_sha256
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    paper_id,
                    note_id,
                    annotation_type,
                    page_number,
                    color,
                    selected_text,
                    prefix_text,
                    suffix_text,
                    json.dumps(rects, ensure_ascii=False),
                    comment_text,
                    now,
                    now,
                    file_hash,
                ),
            )
            return int(self.connection.last_insert_rowid())
        except BaseException:
            self.connection.execute("DELETE FROM paper_notes WHERE id=?", (note_id,))
            raise

    def update_annotation(
        self, annotation_id: int, *, color: str | None, comment_text: str | None
    ) -> None:
        row = self.connection.execute(
            """
            SELECT note_id, annotation_type, page_number, selected_text,
                   color, comment_text, file_id, paper_id
            FROM pdf_annotations WHERE id=?
            """,
            (annotation_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Annotation not found")
        next_color = str(row[4]) if color is None else color
        next_comment = str(row[5]) if comment_text is None else comment_text
        if row[0] is not None:
            self.library.save_note(
                int(str(row[7])),
                self._note_body(
                    str(row[1]),
                    int(str(row[2])),
                    str(row[3]),
                    next_comment,
                    int(str(row[6])),
                ),
                note_id=int(str(row[0])),
            )
        self.connection.execute(
            "UPDATE pdf_annotations SET color=?, comment_text=?, updated_at=? WHERE id=?",
            (next_color, next_comment, utc_now(), annotation_id),
        )

    def delete_annotation(self, annotation_id: int) -> None:
        row = self.connection.execute(
            "SELECT note_id FROM pdf_annotations WHERE id=?", (annotation_id,)
        ).fetchone()
        if row is None:
            return
        with transaction(self.connection):
            self.connection.execute("DELETE FROM pdf_annotations WHERE id=?", (annotation_id,))
            if row[0] is not None:
                self.connection.execute("DELETE FROM paper_notes WHERE id=?", (row[0],))

    @staticmethod
    def _note_body(
        annotation_type: str,
        page_number: int,
        selected_text: str,
        comment_text: str,
        file_id: int,
    ) -> str:
        labels = {"highlight": "高亮", "underline": "划线", "comment": "批注"}
        parts = [
            f"[PDF 第 {page_number} 页 · {labels[annotation_type]} · 文件 {file_id}]",
            selected_text,
        ]
        if comment_text:
            parts.append(comment_text)
        return "\n".join(part for part in parts if part)
