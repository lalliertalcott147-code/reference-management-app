from __future__ import annotations

from dataclasses import dataclass

import apsw

from ..search.merge import merge_records, weak_fingerprint
from ..search.models import PaperRecord
from ..search.persistence import SearchResultRepository
from ..storage.repositories import normalize_doi, normalize_title
from .models import ImportPreview, ImportReport
from .parsers import parse_wos_export


@dataclass(frozen=True)
class ExistingMatch:
    paper_id: int
    conflicts: int


class WosImportService:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection
        self.persistence = SearchResultRepository(connection)

    def _match(self, record: PaperRecord) -> ExistingMatch | None:
        doi = normalize_doi(record.doi)
        row = None
        if doi:
            row = self.connection.execute(
                """
                SELECT id, title_original, journal_title, publication_year
                FROM papers WHERE doi=?
                """,
                (doi,),
            ).fetchone()
        if row is None and record.wos_uid:
            row = self.connection.execute(
                """
                SELECT id, title_original, journal_title, publication_year
                FROM papers WHERE wos_uid=?
                """,
                (record.wos_uid,),
            ).fetchone()
        if row is None:
            row = self.connection.execute(
                """
                SELECT id, title_original, journal_title, publication_year
                FROM papers WHERE weak_fingerprint=? OR
                    (normalized_title=? AND publication_year IS ?)
                ORDER BY id LIMIT 1
                """,
                (weak_fingerprint(record), normalize_title(record.title), record.year),
            ).fetchone()
        if row is None:
            return None
        conflicts = 0
        existing_values = (row[1], row[2], row[3])
        incoming_values = (record.title, record.journal, record.year)
        for existing, incoming in zip(existing_values, incoming_values, strict=True):
            if existing not in (None, "") and incoming not in (None, "") and existing != incoming:
                conflicts += 1
        return ExistingMatch(int(row[0]), conflicts)

    def preview(self, filename: str, data: bytes) -> ImportPreview:
        parsed = parse_wos_export(filename, data)
        new = 0
        duplicates = 0
        conflicts = 0
        missing_doi = 0
        for record in parsed.records:
            if not normalize_doi(record.doi):
                missing_doi += 1
            match = self._match(record)
            if match is None:
                new += 1
            else:
                duplicates += 1
                conflicts += match.conflicts
        return ImportPreview(
            parsed.format,
            len(parsed.records),
            new,
            duplicates,
            missing_doi,
            conflicts,
            parsed.records,
            parsed.issues,
        )

    def confirm(self, preview: ImportPreview) -> ImportReport:
        added = 0
        updated = 0
        skipped = 0
        for record in preview.records:
            match = self._match(record)
            merged = merge_records([record])[0]
            self.persistence.save(merged)
            if match is None:
                added += 1
            elif match.conflicts:
                updated += 1
            else:
                skipped += 1
        return ImportReport(
            total=preview.total + len(preview.issues),
            added=added,
            updated=updated,
            skipped=skipped,
            failed=len(preview.issues),
            issues=preview.issues,
        )

    def import_file(self, filename: str, data: bytes) -> ImportReport:
        return self.confirm(self.preview(filename, data))
