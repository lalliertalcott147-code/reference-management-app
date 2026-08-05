from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any

import apsw

from .database import transaction, utc_now


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def normalize_doi(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized.rstrip(" .;,") or None


class SettingsRepository:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    def set(self, key: str, value: Any) -> None:
        self.connection.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at) VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json=excluded.value_json,
                updated_at=excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), utc_now()),
        )

    def get(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute(
            "SELECT value_json FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        return default if row is None else json.loads(str(row[0]))


@dataclass(frozen=True)
class PaperDraft:
    title: str
    doi: str | None = None
    wos_uid: str | None = None
    journal: str | None = None
    year: int | None = None


class PaperRepository:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    def create(self, draft: PaperDraft) -> int:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO papers(
                doi, wos_uid, title_original, normalized_title, journal_title,
                publication_year, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalize_doi(draft.doi),
                draft.wos_uid,
                draft.title,
                normalize_title(draft.title),
                draft.journal,
                draft.year,
                now,
                now,
            ),
        )
        return int(self.connection.last_insert_rowid())

    def create_with_library(self, draft: PaperDraft, library_name: str) -> tuple[int, int]:
        now = utc_now()
        with transaction(self.connection):
            paper_id = self.create(draft)
            self.connection.execute(
                "INSERT INTO libraries(name, created_at, updated_at) VALUES(?, ?, ?)",
                (library_name, now, now),
            )
            library_id = int(self.connection.last_insert_rowid())
            self.connection.execute(
                "INSERT INTO library_papers(library_id, paper_id, added_at) VALUES(?, ?, ?)",
                (library_id, paper_id, now),
            )
        return paper_id, library_id
