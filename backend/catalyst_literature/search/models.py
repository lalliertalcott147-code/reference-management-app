from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SearchField = Literal["topic", "title", "author", "doi"]
SourceName = Literal["wos", "openalex", "crossref", "wos_export", "pdf"]


@dataclass(frozen=True)
class SearchQuery:
    text: str
    field: SearchField = "topic"
    page: int = 1
    page_size: int = 20
    cursor: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    sort: str = "relevance"

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Search text must not be empty")
        if not 1 <= self.page_size <= 50:
            raise ValueError("Page size must be between 1 and 50")
        if self.page < 1:
            raise ValueError("Page must be positive")
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("Invalid publication year range")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaperRecord:
    source: SourceName
    source_id: str
    title: str
    doi: str | None = None
    wos_uid: str | None = None
    authors: tuple[str, ...] = ()
    journal: str | None = None
    year: int | None = None
    abstract: str | None = None
    url: str | None = None
    citations: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuotaStatus:
    limit: int | None = None
    remaining: int | None = None
    reset_seconds: int | None = None


@dataclass(frozen=True)
class SearchPage:
    source: SourceName
    records: tuple[PaperRecord, ...]
    total: int | None
    next_cursor: str | None = None
    quota: QuotaStatus = QuotaStatus()


@dataclass(frozen=True)
class SourceStatus:
    source: SourceName
    state: Literal["success", "cache", "offline", "missing_key", "limited", "failed"]
    message: str
    fetched_at: str | None = None


class SourceError(RuntimeError):
    def __init__(self, source: SourceName, code: str, message: str) -> None:
        super().__init__(message)
        self.source = source
        self.code = code
