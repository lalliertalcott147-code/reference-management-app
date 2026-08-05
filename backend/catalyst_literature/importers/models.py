from __future__ import annotations

from dataclasses import dataclass

from ..search.models import PaperRecord


class ImportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportIssue:
    record_number: int | None
    field: str | None
    message: str


@dataclass(frozen=True)
class ParsedImport:
    format: str
    records: tuple[PaperRecord, ...]
    issues: tuple[ImportIssue, ...]


@dataclass(frozen=True)
class ImportPreview:
    format: str
    total: int
    new: int
    duplicates: int
    missing_doi: int
    conflicts: int
    records: tuple[PaperRecord, ...]
    issues: tuple[ImportIssue, ...]


@dataclass(frozen=True)
class ImportReport:
    total: int
    added: int
    updated: int
    skipped: int
    failed: int
    issues: tuple[ImportIssue, ...]
