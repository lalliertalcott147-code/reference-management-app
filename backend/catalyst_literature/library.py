from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import apsw

from .config import AppPaths
from .storage.database import require_row, transaction, utc_now
from .storage.repositories import normalize_title


@dataclass(frozen=True)
class LibraryRecord:
    id: int
    name: str
    sort_order: int
    deleted_at: str | None
    paper_count: int


def refresh_paper_fts(connection: apsw.Connection, paper_id: int) -> None:
    paper = connection.execute(
        "SELECT title_original, coalesce(title_zh, ''), coalesce(journal_title, '') "
        "FROM papers WHERE id=?",
        (paper_id,),
    ).fetchone()
    if paper is None:
        return
    authors = "; ".join(
        str(row[0])
        for row in connection.execute(
            """
            SELECT a.display_name FROM authors a
            JOIN paper_authors pa ON pa.author_id=a.id
            WHERE pa.paper_id=? ORDER BY pa.author_order
            """,
            (paper_id,),
        )
    )
    abstracts = "\n".join(
        str(row[0])
        for row in connection.execute("SELECT content FROM abstracts WHERE paper_id=?", (paper_id,))
    )
    translations = "\n".join(
        str(row[0])
        for row in connection.execute(
            "SELECT translated_text FROM translations WHERE paper_id=?", (paper_id,)
        )
    )
    tags = "; ".join(
        str(row[0])
        for row in connection.execute(
            """
            SELECT DISTINCT t.name FROM tags t JOIN paper_tags pt ON pt.tag_id=t.id
            WHERE pt.paper_id=? ORDER BY t.name
            """,
            (paper_id,),
        )
    )
    notes = "\n".join(
        str(row[0])
        for row in connection.execute("SELECT body FROM paper_notes WHERE paper_id=?", (paper_id,))
    )
    connection.execute("DELETE FROM paper_fts WHERE paper_id=?", (paper_id,))
    connection.execute(
        """
        INSERT INTO paper_fts(
            paper_id, title_original, title_zh, authors, journal,
            abstract_text, translation_text, tags, notes
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (paper_id, paper[0], paper[1], authors, paper[2], abstracts, translations, tags, notes),
    )


class LibraryService:
    def __init__(self, connection: apsw.Connection, paths: AppPaths) -> None:
        self.connection = connection
        self.paths = paths

    def list_libraries(self, *, include_deleted: bool = False) -> list[LibraryRecord]:
        where = "" if include_deleted else "WHERE l.deleted_at IS NULL"
        return [
            LibraryRecord(int(row[0]), str(row[1]), int(row[2]), row[3], int(row[4]))
            for row in self.connection.execute(
                f"""
                SELECT l.id, l.name, l.sort_order, l.deleted_at, count(lp.paper_id)
                FROM libraries l LEFT JOIN library_papers lp ON lp.library_id=l.id
                {where} GROUP BY l.id ORDER BY l.sort_order, l.id
                """
            )
        ]

    def create_library(self, name: str) -> int:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise ValueError("Library name must not be empty")
        row = require_row(
            self.connection.execute(
                "SELECT coalesce(max(sort_order), -1) + 1 FROM libraries WHERE deleted_at IS NULL"
            ).fetchone(),
            "choosing library order",
        )
        now = utc_now()
        self.connection.execute(
            "INSERT INTO libraries(name, sort_order, created_at, updated_at) VALUES(?, ?, ?, ?)",
            (cleaned, int(row[0]), now, now),
        )
        return int(self.connection.last_insert_rowid())

    def rename_library(self, library_id: int, name: str) -> None:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise ValueError("Library name must not be empty")
        self.connection.execute(
            "UPDATE libraries SET name=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (cleaned, utc_now(), library_id),
        )

    def reorder(self, ordered_ids: list[int]) -> None:
        with transaction(self.connection):
            for order, library_id in enumerate(ordered_ids):
                self.connection.execute(
                    """
                    UPDATE libraries SET sort_order=?, updated_at=?
                    WHERE id=? AND deleted_at IS NULL
                    """,
                    (order, utc_now(), library_id),
                )

    def move_to_trash(self, library_id: int) -> None:
        self.connection.execute(
            "UPDATE libraries SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (utc_now(), utc_now(), library_id),
        )

    def restore_library(self, library_id: int) -> None:
        self.connection.execute(
            "UPDATE libraries SET deleted_at=NULL, updated_at=? WHERE id=?",
            (utc_now(), library_id),
        )

    def purge_expired(self, *, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=30)
        ids = [
            int(row[0])
            for row in self.connection.execute(
                "SELECT id FROM libraries WHERE deleted_at IS NOT NULL AND deleted_at <= ?",
                (cutoff.isoformat(),),
            )
        ]
        for library_id in ids:
            self.connection.execute("DELETE FROM libraries WHERE id=?", (library_id,))
        return len(ids)

    def add_paper(self, library_id: int, paper_id: int) -> bool:
        self._require_active_library(library_id)
        if self.connection.execute(
            "SELECT 1 FROM papers WHERE id=?", (paper_id,)
        ).fetchone() is None:
            raise LookupError("Paper not found")
        self.connection.execute(
            """
            INSERT INTO library_papers(library_id, paper_id, added_at)
            VALUES(?, ?, ?) ON CONFLICT(library_id, paper_id) DO NOTHING
            """,
            (library_id, paper_id, utc_now()),
        )
        return self.connection.changes() > 0

    def remove_paper(self, library_id: int, paper_id: int) -> None:
        self.connection.execute(
            "DELETE FROM library_papers WHERE library_id=? AND paper_id=?",
            (library_id, paper_id),
        )

    def list_papers(
        self, library_id: int | None = None, query: str | None = None
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        join = ""
        if library_id is not None:
            join += " JOIN library_papers lp ON lp.paper_id=p.id "
            clauses.append("lp.library_id=?")
            parameters.append(library_id)
        if query:
            join += " JOIN paper_fts f ON f.paper_id=p.id "
            clauses.append("paper_fts MATCH ?")
            parameters.append(query)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return [
            {
                "id": row[0],
                "title": row[1],
                "journal": row[2],
                "year": row[3],
                "doi": row[4],
                "liked": bool(row[5]),
                "saved": bool(row[6]),
                "reading_status": row[7],
                  "has_pdf": bool(row[8]),
                  "file_id": row[9],
                  "note_id": row[10],
                  "note": row[11] or "",
            }
            for row in self.connection.execute(
                f"""
                SELECT DISTINCT p.id, p.title_original, p.journal_title,
                    p.publication_year, p.doi, coalesce(s.liked, 0),
                    coalesce(s.saved, 0), coalesce(s.reading_status, 'unread'),
                      EXISTS(SELECT 1 FROM paper_files pf WHERE pf.paper_id=p.id),
                      (SELECT pf.file_id FROM paper_files pf WHERE pf.paper_id=p.id
                       ORDER BY CASE pf.version_role WHEN 'primary' THEN 0 ELSE 1 END,
                                pf.created_at DESC LIMIT 1),
                      (SELECT n.id FROM paper_notes n WHERE n.paper_id=p.id
                     ORDER BY n.updated_at DESC LIMIT 1),
                    (SELECT n.body FROM paper_notes n WHERE n.paper_id=p.id
                     ORDER BY n.updated_at DESC LIMIT 1)
                FROM papers p
                LEFT JOIN user_paper_state s ON s.paper_id=p.id
                {join}{where} ORDER BY p.updated_at DESC
                """,
                parameters,
            )
        ]

    def set_state(
        self,
        paper_id: int,
        *,
        liked: bool,
        disliked: bool,
        saved: bool,
        reading_status: str,
    ) -> None:
        if reading_status not in {"unread", "reading", "read"}:
            raise ValueError("Invalid reading status")
        self.connection.execute(
            """
            INSERT INTO user_paper_state(
                paper_id, liked, disliked, saved, reading_status, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET liked=excluded.liked,
                disliked=excluded.disliked, saved=excluded.saved,
                reading_status=excluded.reading_status, updated_at=excluded.updated_at
            """,
            (paper_id, int(liked), int(disliked), int(saved), reading_status, utc_now()),
        )

    def create_tag(self, name: str) -> int:
        cleaned = " ".join(name.split())
        normalized = normalize_title(cleaned)
        if not normalized:
            raise ValueError("Tag name must not be empty")
        self.connection.execute(
            """
            INSERT INTO tags(name, normalized_name, created_at) VALUES(?, ?, ?)
            ON CONFLICT(normalized_name) DO NOTHING
            """,
            (cleaned, normalized, utc_now()),
        )
        row = require_row(
            self.connection.execute(
                "SELECT id FROM tags WHERE normalized_name=?", (normalized,)
            ).fetchone(),
            "reading tag",
        )
        return int(row[0])

    def tag_papers(self, tag_id: int, paper_ids: list[int], library_id: int | None = None) -> None:
        with transaction(self.connection):
            for paper_id in paper_ids:
                self.connection.execute(
                    """
                    INSERT INTO paper_tags(paper_id, tag_id, library_id, created_at)
                    VALUES(?, ?, ?, ?) ON CONFLICT DO NOTHING
                    """,
                    (paper_id, tag_id, library_id, utc_now()),
                )
                refresh_paper_fts(self.connection, paper_id)

    def merge_tags(self, source_tag_id: int, target_tag_id: int) -> None:
        if source_tag_id == target_tag_id:
            return
        paper_ids = [
            int(row[0])
            for row in self.connection.execute(
                "SELECT DISTINCT paper_id FROM paper_tags WHERE tag_id IN (?, ?)",
                (source_tag_id, target_tag_id),
            )
        ]
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT OR IGNORE INTO paper_tags(paper_id, tag_id, library_id, created_at)
                SELECT paper_id, ?, library_id, created_at FROM paper_tags WHERE tag_id=?
                """,
                (target_tag_id, source_tag_id),
            )
            self.connection.execute("DELETE FROM tags WHERE id=?", (source_tag_id,))
            for paper_id in paper_ids:
                refresh_paper_fts(self.connection, paper_id)

    def save_note(
        self,
        paper_id: int,
        body: str,
        *,
        note_id: int | None = None,
        library_id: int | None = None,
    ) -> tuple[int, int]:
        now = utc_now()
        with transaction(self.connection):
            if note_id is None:
                self.connection.execute(
                    """
                    INSERT INTO paper_notes(
                        paper_id, library_id, body, version, created_at, updated_at
                    ) VALUES(?, ?, ?, 1, ?, ?)
                    """,
                    (paper_id, library_id, body, now, now),
                )
                note_id = int(self.connection.last_insert_rowid())
                version = 1
            else:
                row = require_row(
                    self.connection.execute(
                        "SELECT version FROM paper_notes WHERE id=? AND paper_id=?",
                        (note_id, paper_id),
                    ).fetchone(),
                    "updating note",
                )
                version = int(row[0]) + 1
                self.connection.execute(
                    "UPDATE paper_notes SET body=?, version=?, updated_at=? WHERE id=?",
                    (body, version, now, note_id),
                )
            self.connection.execute(
                """
                INSERT INTO paper_note_versions(note_id, version, body, saved_at)
                VALUES(?, ?, ?, ?)
                """,
                (note_id, version, body, now),
            )
            refresh_paper_fts(self.connection, paper_id)
        return note_id, version

    def append_note(
        self, paper_id: int, body: str, *, library_id: int | None = None
    ) -> tuple[int, int]:
        addition = body.strip()
        if not addition:
            raise ValueError("Note text must not be empty")
        if library_id is None:
            row = self.connection.execute(
                """
                SELECT id, body FROM paper_notes WHERE paper_id=?
                ORDER BY updated_at DESC, id DESC LIMIT 1
                """,
                (paper_id,),
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT id, body FROM paper_notes WHERE paper_id=? AND library_id=?
                ORDER BY updated_at DESC, id DESC LIMIT 1
                """,
                (paper_id, library_id),
            ).fetchone()
        if row is None:
            return self.save_note(paper_id, addition, library_id=library_id)
        current = str(row[1]).rstrip()
        combined = f"{current}\n\n{addition}" if current else addition
        return self.save_note(paper_id, combined, note_id=int(row[0]), library_id=library_id)

    def get_workspace(self, library_id: int | None) -> dict[str, object]:
        workspace_id = self._get_or_create_workspace_id(library_id)
        row = require_row(
            self.connection.execute(
                """
                SELECT body, note_x, note_y, note_width, note_height, version, updated_at
                FROM library_workspaces WHERE id=?
                """,
                (workspace_id,),
            ).fetchone(),
            "reading library workspace",
        )
        return {
            "library_id": library_id,
            "body": str(row[0]),
            "note_x": float(row[1]),
            "note_y": float(row[2]),
            "note_width": float(row[3]),
            "note_height": float(row[4]),
            "version": int(row[5]),
            "updated_at": str(row[6]),
            "cards": self._workspace_cards(workspace_id, library_id),
            "elements": self._workspace_elements(workspace_id),
        }

    def save_workspace(
        self,
        library_id: int | None,
        *,
        body: str,
        note_x: float,
        note_y: float,
        note_width: float,
        note_height: float,
    ) -> int:
        workspace_id = self._get_or_create_workspace_id(library_id)
        now = utc_now()
        self.connection.execute(
            """
            UPDATE library_workspaces SET
                body=?, note_x=?, note_y=?, note_width=?, note_height=?,
                version=version + 1, updated_at=? WHERE id=?
            """,
            (body, note_x, note_y, note_width, note_height, now, workspace_id),
        )
        row = require_row(
            self.connection.execute(
                "SELECT version FROM library_workspaces WHERE id=?", (workspace_id,)
            ).fetchone(),
            "saving library workspace",
        )
        return int(row[0])

    def add_workspace_card(self, library_id: int | None, paper_id: int) -> int:
        workspace_id = self._get_or_create_workspace_id(library_id)
        if library_id is None:
            paper_exists = self.connection.execute(
                "SELECT 1 FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        else:
            paper_exists = self.connection.execute(
                "SELECT 1 FROM library_papers WHERE library_id=? AND paper_id=?",
                (library_id, paper_id),
            ).fetchone()
        if paper_exists is None:
            raise ValueError("Paper is not part of this library")
        count = int(
            require_row(
                self.connection.execute(
                    "SELECT count(*) FROM library_workspace_cards WHERE workspace_id=?",
                    (workspace_id,),
                ).fetchone(),
                "positioning workspace card",
            )[0]
        )
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO library_workspace_cards(
                workspace_id, paper_id, x, y, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                paper_id,
                580 + (count % 2) * 370,
                24 + (count // 2) * 390,
                now,
                now,
            ),
        )
        return int(self.connection.last_insert_rowid())

    def update_workspace_card(
        self, card_id: int, *, x: float, y: float, width: float, height: float
    ) -> None:
        self.connection.execute(
            """
            UPDATE library_workspace_cards
            SET x=?, y=?, width=?, height=?, updated_at=? WHERE id=?
            """,
            (x, y, width, height, utc_now(), card_id),
        )
        if self.connection.changes() == 0:
            raise LookupError("Workspace card not found")

    def delete_workspace_card(self, card_id: int) -> None:
        self.connection.execute("DELETE FROM library_workspace_cards WHERE id=?", (card_id,))
        if self.connection.changes() == 0:
            raise LookupError("Workspace card not found")

    def create_workspace_element(
        self,
        library_id: int | None,
        *,
        element_type: str,
        x: float,
        y: float,
        width: float,
        height: float,
        content: str,
        rotation: float = 0,
        text_color: str = "#1F3633",
        fill_color: str = "#FFFFFF",
        border_color: str = "#315F59",
        border_width: float = 2,
        font_size: float = 18,
        font_family: str = "Microsoft YaHei",
        text_align: str = "left",
        z_index: int = 1,
        group_id: str | None = None,
    ) -> int:
        if element_type not in {"text", "rectangle", "ellipse", "line", "arrow", "image"}:
            raise ValueError("Unsupported workspace element type")
        if element_type == "image" and not content.startswith(
            (
                "data:image/png;base64,",
                "data:image/jpeg;base64,",
                "data:image/webp;base64,",
                "data:image/gif;base64,",
            )
        ):
            raise ValueError("Unsupported workspace image")
        workspace_id = self._get_or_create_workspace_id(library_id)
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO library_workspace_elements(
                workspace_id, element_type, x, y, width, height,
                rotation, content, text_color, fill_color, border_color,
                border_width, font_size, font_family, text_align, z_index,
                group_id, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                element_type,
                x,
                y,
                width,
                height,
                rotation,
                content,
                text_color,
                fill_color,
                border_color,
                border_width,
                font_size,
                font_family,
                text_align,
                z_index,
                group_id,
                now,
                now,
            ),
        )
        return int(self.connection.last_insert_rowid())

    def update_workspace_element(
        self,
        element_id: int,
        *,
        element_type: str,
        x: float,
        y: float,
        width: float,
        height: float,
        content: str,
        rotation: float = 0,
        text_color: str = "#1F3633",
        fill_color: str = "#FFFFFF",
        border_color: str = "#315F59",
        border_width: float = 2,
        font_size: float = 18,
        font_family: str = "Microsoft YaHei",
        text_align: str = "left",
        z_index: int = 1,
        group_id: str | None = None,
    ) -> None:
        if element_type not in {"text", "rectangle", "ellipse", "line", "arrow", "image"}:
            raise ValueError("Unsupported workspace element type")
        if element_type == "image" and not content.startswith(
            (
                "data:image/png;base64,",
                "data:image/jpeg;base64,",
                "data:image/webp;base64,",
                "data:image/gif;base64,",
            )
        ):
            raise ValueError("Unsupported workspace image")
        self.connection.execute(
            """
            UPDATE library_workspace_elements SET
                element_type=?, x=?, y=?, width=?, height=?, rotation=?,
                content=?, text_color=?, fill_color=?, border_color=?,
                border_width=?, font_size=?, font_family=?, text_align=?,
                z_index=?, group_id=?, deleted_at=NULL, updated_at=? WHERE id=?
            """,
            (
                element_type,
                x,
                y,
                width,
                height,
                rotation,
                content,
                text_color,
                fill_color,
                border_color,
                border_width,
                font_size,
                font_family,
                text_align,
                z_index,
                group_id,
                utc_now(),
                element_id,
            ),
        )
        if self.connection.changes() == 0:
            raise LookupError("Workspace element not found")

    def delete_workspace_element(self, element_id: int) -> None:
        self.connection.execute(
            """
            UPDATE library_workspace_elements SET deleted_at=?, updated_at=?
            WHERE id=? AND deleted_at IS NULL
            """,
            (utc_now(), utc_now(), element_id),
        )
        if self.connection.changes() == 0:
            raise LookupError("Workspace element not found")

    def _require_active_library(self, library_id: int) -> None:
        if self.connection.execute(
            "SELECT 1 FROM libraries WHERE id=? AND deleted_at IS NULL", (library_id,)
        ).fetchone() is None:
            raise LookupError("Library not found")

    def _get_or_create_workspace_id(self, library_id: int | None) -> int:
        if library_id is not None:
            self._require_active_library(library_id)
        scope_type = "all" if library_id is None else "library"
        row = self.connection.execute(
            """
            SELECT id FROM library_workspaces
            WHERE scope_type=? AND library_id IS ?
            """,
            (scope_type, library_id),
        ).fetchone()
        if row is not None:
            return int(row[0])
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO library_workspaces(
                scope_type, library_id, created_at, updated_at
            ) VALUES(?, ?, ?, ?)
            """,
            (scope_type, library_id, now, now),
        )
        return int(self.connection.last_insert_rowid())

    def _workspace_cards(
        self, workspace_id: int, library_id: int | None
    ) -> list[dict[str, object]]:
        cards: list[dict[str, object]] = []
        rows = self.connection.execute(
            """
            SELECT c.id, c.paper_id, c.x, c.y, c.width, c.height,
                p.title_original, p.title_zh,
                (SELECT a.content FROM abstracts a WHERE a.paper_id=p.id
                 ORDER BY a.is_preferred DESC, a.id LIMIT 1),
                (SELECT t.translated_text FROM translations t
                 WHERE t.paper_id=p.id AND t.field_name='abstract'
                 ORDER BY t.id DESC LIMIT 1),
                (SELECT pf.file_id FROM paper_files pf WHERE pf.paper_id=p.id
                 ORDER BY CASE pf.version_role WHEN 'primary' THEN 0 ELSE 1 END,
                          pf.created_at DESC LIMIT 1)
            FROM library_workspace_cards c
            JOIN papers p ON p.id=c.paper_id
            WHERE c.workspace_id=? ORDER BY c.id
            """,
            (workspace_id,),
        )
        for row in rows:
            paper_id = int(row[1])
            note_query = """
                SELECT id, body, updated_at FROM paper_notes
                WHERE paper_id=? AND library_id IS NULL
                ORDER BY updated_at DESC, id DESC
            """
            note_parameters: tuple[int, ...] = (paper_id,)
            if library_id is not None:
                note_query = """
                    SELECT id, body, updated_at FROM paper_notes
                    WHERE paper_id=? AND library_id=?
                    ORDER BY updated_at DESC, id DESC
                """
                note_parameters = (paper_id, library_id)
            notes = [
                {
                    "id": int(note[0]),
                    "body": str(note[1]),
                    "updated_at": str(note[2]),
                }
                for note in self.connection.execute(note_query, note_parameters)
            ]
            cards.append(
                {
                    "id": int(row[0]),
                    "paper_id": paper_id,
                    "x": float(row[2]),
                    "y": float(row[3]),
                    "width": float(row[4]),
                    "height": float(row[5]),
                    "title": str(row[6]),
                    "title_translation": None if row[7] is None else str(row[7]),
                    "abstract": "" if row[8] is None else str(row[8]),
                    "abstract_translation": None if row[9] is None else str(row[9]),
                    "file_id": None if row[10] is None else int(row[10]),
                    "notes": notes,
                }
            )
        return cards

    def _workspace_elements(self, workspace_id: int) -> list[dict[str, object]]:
        return [
            {
                "id": int(row[0]),
                "element_type": str(row[1]),
                "x": float(row[2]),
                "y": float(row[3]),
                "width": float(row[4]),
                "height": float(row[5]),
                "rotation": float(row[6]),
                "content": str(row[7]),
                "text_color": str(row[8]),
                "fill_color": str(row[9]),
                "border_color": str(row[10]),
                "border_width": float(row[11]),
                "font_size": float(row[12]),
                "font_family": str(row[13]),
                "text_align": str(row[14]),
                "z_index": int(row[15]),
                "group_id": None if row[16] is None else str(row[16]),
            }
            for row in self.connection.execute(
                """
                SELECT id, element_type, x, y, width, height, rotation,
                       content, text_color, fill_color, border_color,
                       border_width, font_size, font_family, text_align,
                       z_index, group_id
                FROM library_workspace_elements
                WHERE workspace_id=? AND deleted_at IS NULL ORDER BY z_index, id
                """,
                (workspace_id,),
            )
        ]

    def export(self, paper_ids: list[int], format_name: str) -> tuple[str, bytes]:
        if not paper_ids:
            raise ValueError("Select at least one paper to export")
        placeholders = ",".join("?" for _ in paper_ids)
        rows = self.connection.execute(
            f"""
            SELECT p.id, p.title_original, p.journal_title, p.publication_year,
                p.doi, group_concat(a.display_name, '; ')
            FROM papers p
            LEFT JOIN paper_authors pa ON pa.paper_id=p.id
            LEFT JOIN authors a ON a.id=pa.author_id
            WHERE p.id IN ({placeholders}) GROUP BY p.id ORDER BY p.id
            """,
            paper_ids,
        ).fetchall()
        if format_name == "csv":
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(["Title", "Authors", "Journal", "Year", "DOI"])
            for row in rows:
                writer.writerow([row[1], row[5] or "", row[2] or "", row[3] or "", row[4] or ""])
            return "papers.csv", output.getvalue().encode("utf-8-sig")
        if format_name == "ris":
            lines: list[str] = []
            for row in rows:
                lines.extend(["TY  - JOUR", f"TI  - {row[1]}"])
                for author in str(row[5] or "").split("; "):
                    if author:
                        lines.append(f"AU  - {author}")
                if row[2]:
                    lines.append(f"JO  - {row[2]}")
                if row[3]:
                    lines.append(f"PY  - {row[3]}")
                if row[4]:
                    lines.append(f"DO  - {row[4]}")
                lines.extend(["ER  -", ""])
            return "papers.ris", "\r\n".join(lines).encode()
        if format_name == "bibtex":
            entries: list[str] = []
            for row in rows:
                fields = {
                    "title": row[1],
                    "author": str(row[5] or "").replace("; ", " and "),
                    "journal": row[2],
                    "year": row[3],
                    "doi": row[4],
                }
                body = ",\n".join(
                    f"  {key} = {{{self._bibtex_escape(str(value))}}}"
                    for key, value in fields.items()
                    if value not in (None, "")
                )
                entries.append(f"@article{{catalyst{row[0]},\n{body}\n}}")
            return "papers.bib", ("\n\n".join(entries) + "\n").encode()
        raise ValueError("Unsupported export format")

    @staticmethod
    def _bibtex_escape(value: str) -> str:
        return value.replace("\\", r"\textbackslash{}").replace("{", r"\{").replace("}", r"\}")

    def storage_usage(self) -> dict[str, int]:
        return {
            "database": _tree_size(self.paths.data),
            "pdf": _tree_size(self.paths.library / "pdfs"),
            "models": _tree_size(self.paths.models),
            "cache": _tree_size(self.paths.cache) + _file_size(self.paths.data / "cache.db"),
            "backups": _tree_size(self.paths.backups),
            "logs": _tree_size(self.paths.logs),
        }


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def _tree_size(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
