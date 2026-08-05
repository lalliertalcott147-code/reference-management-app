from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .cache import SearchCache
from .merge import MergedPaper, merge_records
from .models import PaperRecord, SearchPage, SearchQuery, SourceError, SourceName, SourceStatus


class SearchSource(Protocol):
    name: SourceName

    def search(self, query: SearchQuery) -> SearchPage: ...


@dataclass(frozen=True)
class CombinedSearchResult:
    papers: tuple[MergedPaper, ...]
    statuses: tuple[SourceStatus, ...]


class SearchService:
    def __init__(self, sources: tuple[SearchSource, ...], cache: SearchCache) -> None:
        self.sources = sources
        self.cache = cache

    def search(
        self,
        query: SearchQuery,
        *,
        refresh: bool = False,
        online: bool = True,
    ) -> CombinedSearchResult:
        records: list[PaperRecord] = []
        statuses: list[SourceStatus] = []
        for source in self.sources:
            cached = None if refresh else self.cache.get(source.name, query)
            if cached is not None:
                records.extend(cached.page.records)
                statuses.append(
                    SourceStatus(
                        source.name, "cache", "Using local search cache", cached.fetched_at
                    )
                )
                continue
            if not online:
                statuses.append(SourceStatus(source.name, "offline", "No unexpired local cache"))
                continue
            try:
                page = source.search(query)
            except SourceError as error:
                state = error.code if error.code in {"missing_key", "limited"} else "failed"
                statuses.append(SourceStatus(source.name, state, str(error)))  # type: ignore[arg-type]
                continue
            except Exception as error:  # isolate one external source from the others
                statuses.append(SourceStatus(source.name, "failed", str(error)))
                continue
            self.cache.put(query, page)
            records.extend(page.records)
            statuses.append(
                SourceStatus(source.name, "success", f"Received {len(page.records)} records")
            )
        return CombinedSearchResult(tuple(merge_records(records)), tuple(statuses))
