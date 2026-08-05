from __future__ import annotations

import hashlib
import json

import apsw

from ..storage.database import require_row, transaction, utc_now
from ..storage.repositories import normalize_title
from .merge import MergedPaper, weak_fingerprint


class SearchResultRepository:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    def _find_paper(self, paper: MergedPaper) -> int | None:
        if paper.doi:
            row = self.connection.execute(
                "SELECT id FROM papers WHERE doi=?", (paper.doi,)
            ).fetchone()
            if row is not None:
                return int(row[0])
        if paper.wos_uid:
            row = self.connection.execute(
                "SELECT id FROM papers WHERE wos_uid=?", (paper.wos_uid,)
            ).fetchone()
            if row is not None:
                return int(row[0])
        row = self.connection.execute(
            """
            SELECT id FROM papers
            WHERE normalized_title=? AND publication_year IS ?
            ORDER BY id LIMIT 1
            """,
            (normalize_title(paper.title), paper.year),
        ).fetchone()
        return None if row is None else int(row[0])

    def save(self, paper: MergedPaper) -> int:
        now = utc_now()
        with transaction(self.connection):
            paper_id = self._find_paper(paper)
            if paper_id is None:
                self.connection.execute(
                    """
                    INSERT INTO papers(
                        doi, wos_uid, title_original, normalized_title,
                        weak_fingerprint, journal_title, publication_year,
                        created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper.doi,
                        paper.wos_uid,
                        paper.title,
                        normalize_title(paper.title),
                        weak_fingerprint(paper.sources[0]),
                        paper.journal,
                        paper.year,
                        now,
                        now,
                    ),
                )
                paper_id = int(self.connection.last_insert_rowid())
            else:
                self.connection.execute(
                    """
                    UPDATE papers SET
                        doi=coalesce(doi, ?), wos_uid=coalesce(wos_uid, ?),
                        title_original=?, normalized_title=?,
                        journal_title=coalesce(?, journal_title),
                        publication_year=coalesce(?, publication_year), updated_at=?
                    WHERE id=?
                    """,
                    (
                        paper.doi,
                        paper.wos_uid,
                        paper.title,
                        normalize_title(paper.title),
                        paper.journal,
                        paper.year,
                        now,
                        paper_id,
                    ),
                )

            source_ids: dict[tuple[str, str], int] = {}
            for source in paper.sources:
                external_id = (
                    source.source_id
                    or hashlib.sha256(f"{source.source}:{paper.identity}".encode()).hexdigest()
                )
                summary = {
                    "title": source.title,
                    "doi": source.doi,
                    "authors": source.authors,
                    "journal": source.journal,
                    "year": source.year,
                    "abstract": source.abstract,
                    "url": source.url,
                }
                self.connection.execute(
                    """
                    INSERT INTO paper_sources(
                        paper_id, source, external_id, source_url,
                        raw_summary_json, fetched_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source, external_id) DO UPDATE SET
                        paper_id=excluded.paper_id,
                        source_url=excluded.source_url,
                        raw_summary_json=excluded.raw_summary_json,
                        fetched_at=excluded.fetched_at
                    """,
                    (
                        paper_id,
                        source.source,
                        external_id,
                        source.url,
                        json.dumps(summary, ensure_ascii=False),
                        now,
                    ),
                )
                row = require_row(
                    self.connection.execute(
                        "SELECT id FROM paper_sources WHERE source=? AND external_id=?",
                        (source.source, external_id),
                    ).fetchone(),
                    "reading saved paper source",
                )
                source_ids[(source.source, source.source_id)] = int(row[0])

            self.connection.execute("DELETE FROM paper_authors WHERE paper_id=?", (paper_id,))
            for order, author_name in enumerate(paper.authors, start=1):
                normalized = normalize_title(author_name)
                author_row = self.connection.execute(
                    "SELECT id FROM authors WHERE normalized_name=? ORDER BY id LIMIT 1",
                    (normalized,),
                ).fetchone()
                if author_row is None:
                    self.connection.execute(
                        "INSERT INTO authors(display_name, normalized_name) VALUES(?, ?)",
                        (author_name, normalized),
                    )
                    author_id = int(self.connection.last_insert_rowid())
                else:
                    author_id = int(author_row[0])
                self.connection.execute(
                    "INSERT INTO paper_authors(paper_id, author_id, author_order) VALUES(?, ?, ?)",
                    (paper_id, author_id, order),
                )

            for source in paper.sources:
                if not source.abstract:
                    continue
                source_id = source_ids[(source.source, source.source_id)]
                digest = hashlib.sha256(source.abstract.encode()).hexdigest()
                self.connection.execute(
                    """
                    INSERT INTO abstracts(
                        paper_id, source_id, language, content, content_hash,
                        is_preferred, created_at
                    ) VALUES(?, ?, 'und', ?, ?, ?, ?)
                    ON CONFLICT(paper_id, source_id, language, content_hash) DO UPDATE SET
                        is_preferred=excluded.is_preferred
                    """,
                    (
                        paper_id,
                        source_id,
                        source.abstract,
                        digest,
                        int(source.abstract == paper.abstract),
                        now,
                    ),
                )

            self.connection.execute("DELETE FROM paper_fts WHERE paper_id=?", (paper_id,))
            self.connection.execute(
                """
                INSERT INTO paper_fts(
                    paper_id, title_original, authors, journal, abstract_text
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    paper.title,
                    "; ".join(paper.authors),
                    paper.journal or "",
                    paper.abstract or "",
                ),
            )
        return paper_id
