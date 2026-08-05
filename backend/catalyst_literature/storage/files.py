from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import apsw

from .database import StorageError, utc_now


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class MissingFile:
    id: int
    sha256: str
    original_name: str
    relative_path: str


class FileRepository:
    def __init__(self, connection: apsw.Connection, library_root: Path) -> None:
        self.connection = connection
        self.library_root = library_root.resolve()

    def register(
        self,
        *,
        sha256: str,
        relative_path: str,
        original_name: str,
        size_bytes: int,
        page_count: int,
    ) -> int:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO files(
                sha256, relative_path, original_name, size_bytes, page_count,
                is_missing, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (sha256, relative_path, original_name, size_bytes, page_count, now, now),
        )
        return int(self.connection.last_insert_rowid())

    def scan_missing(self) -> list[MissingFile]:
        missing: list[MissingFile] = []
        rows = self.connection.execute(
            "SELECT id, sha256, original_name, relative_path FROM files"
        ).fetchall()
        for file_id, digest, original_name, relative_path in rows:
            candidate = (self.library_root / str(relative_path)).resolve()
            absent = not candidate.is_relative_to(self.library_root) or not candidate.is_file()
            self.connection.execute(
                "UPDATE files SET is_missing=?, updated_at=? WHERE id=?",
                (int(absent), utc_now(), file_id),
            )
            if absent:
                missing.append(
                    MissingFile(
                        int(str(file_id)), str(digest), str(original_name), str(relative_path)
                    )
                )
        return missing

    def relink(self, file_id: int, replacement: Path) -> Path:
        row = self.connection.execute(
            "SELECT sha256, relative_path FROM files WHERE id=?", (file_id,)
        ).fetchone()
        if row is None:
            raise StorageError("Unknown PDF record")
        expected_hash, relative_path = str(row[0]), str(row[1])
        if sha256_file(replacement) != expected_hash:
            raise StorageError("Selected PDF content does not match the missing file")
        target = (self.library_root / relative_path).resolve()
        if not target.is_relative_to(self.library_root):
            raise StorageError("Stored PDF path is outside the local library")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".part")
        with replacement.open("rb") as source, temporary.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, target)
        self.connection.execute(
            "UPDATE files SET is_missing=0, updated_at=? WHERE id=?", (utc_now(), file_id)
        )
        return target
