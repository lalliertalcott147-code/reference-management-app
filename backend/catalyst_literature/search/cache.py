from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ..storage.cache import CacheManager
from .models import PaperRecord, QuotaStatus, SearchPage, SearchQuery, SourceName
from .query import query_cache_key


@dataclass(frozen=True)
class CachedSearchPage:
    page: SearchPage
    fetched_at: str


class SearchCache:
    def __init__(self, cache: CacheManager, *, ttl: timedelta = timedelta(days=7)) -> None:
        self.cache = cache
        self.ttl = ttl

    def put(self, query: SearchQuery, page: SearchPage) -> None:
        now = datetime.now(UTC)
        payload = json.dumps(
            {"fetched_at": now.isoformat(), "page": asdict(page)},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.cache.put(
            "search",
            query_cache_key(page.source, query),
            payload,
            expires_at=(now + self.ttl).timestamp(),
        )

    def get(self, source: SourceName, query: SearchQuery) -> CachedSearchPage | None:
        payload = self.cache.get(query_cache_key(source, query))
        if payload is None:
            return None
        raw = cast(dict[str, Any], json.loads(payload))
        page_raw = cast(dict[str, Any], raw["page"])
        records = tuple(
            PaperRecord(
                **{
                    **record,
                    "authors": tuple(record.get("authors", [])),
                }
            )
            for record in cast(list[dict[str, Any]], page_raw["records"])
        )
        page = SearchPage(
            source=cast(SourceName, page_raw["source"]),
            records=records,
            total=page_raw.get("total"),
            next_cursor=page_raw.get("next_cursor"),
            quota=QuotaStatus(**cast(dict[str, Any], page_raw.get("quota", {}))),
        )
        return CachedSearchPage(page, str(raw["fetched_at"]))
