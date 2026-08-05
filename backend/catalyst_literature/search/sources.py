from __future__ import annotations

import html
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from .models import PaperRecord, QuotaStatus, SearchPage, SearchQuery, SourceError, SourceName
from .query import build_openalex_params, build_wos_query
from .transport import JsonResponse, JsonTransport, RateGate, RetryPolicy

WOS_URL = "https://api.clarivate.com/apis/wos-starter/v2/documents"
OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/v1/works"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _integer(value: object) -> int | None:
    try:
        return None if value is None else int(str(value))
    except ValueError:
        return None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _header_integer(headers: Mapping[str, str], *names: str) -> int | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name.lower())
        result = _integer(value)
        if result is not None:
            return result
    return None


def _raise_for_source(source: SourceName, response: JsonResponse) -> None:
    if response.status_code < 400:
        return
    if response.status_code in {401, 403}:
        raise SourceError(source, "invalid_key", "API credential is missing or invalid")
    if response.status_code == 429:
        raise SourceError(source, "limited", "The free request allowance is temporarily exhausted")
    details = _mapping(response.data.get("error"))
    message = _text(details.get("details")) or _text(response.data.get("message"))
    raise SourceError(source, "failed", message or f"Source returned HTTP {response.status_code}")


def restore_inverted_abstract(value: object) -> str | None:
    index = _mapping(value)
    positions: dict[int, str] = {}
    for word, raw_positions in index.items():
        if not isinstance(word, str):
            continue
        for position in _list(raw_positions):
            parsed = _integer(position)
            if parsed is not None and parsed >= 0:
                positions[parsed] = word
    if not positions:
        return None
    return " ".join(positions[position] for position in sorted(positions))


class WosSource:
    name: SourceName = "wos"

    def __init__(
        self,
        api_key: str | None,
        transport: JsonTransport,
        *,
        retry: RetryPolicy | None = None,
        rate_gate: RateGate | None = None,
    ) -> None:
        self.api_key = api_key
        self.transport = transport
        self.retry = retry or RetryPolicy()
        self.rate_gate = rate_gate or RateGate(1)
        self.remaining: int | None = None

    def search(self, query: SearchQuery) -> SearchPage:
        if not self.api_key:
            raise SourceError(self.name, "missing_key", "Web of Science API Key is not configured")
        if self.remaining is not None and self.remaining <= 0:
            raise SourceError(self.name, "limited", "Web of Science free allowance is exhausted")
        self.rate_gate.wait()
        sort_fields = {"relevance": "RS+D", "year_desc": "PY+D", "citations": "TC+D"}
        response = self.retry.get(
            self.transport,
            WOS_URL,
            params={
                "db": "WOS",
                "q": build_wos_query(query),
                "limit": query.page_size,
                "page": query.page,
                "sortField": sort_fields.get(query.sort, "RS+D"),
            },
            headers={"X-ApiKey": self.api_key},
        )
        _raise_for_source(self.name, response)
        records = tuple(self._parse_hit(hit) for hit in _list(response.data.get("hits")))
        metadata = _mapping(response.data.get("metadata"))
        page = _integer(metadata.get("page")) or query.page
        limit = _integer(metadata.get("limit")) or query.page_size
        total = _integer(metadata.get("total"))
        next_cursor = str(page + 1) if total is not None and page * limit < total else None
        quota = QuotaStatus(
            limit=_header_integer(response.headers, "x-ratelimit-limit-day", "x-ratelimit-limit"),
            remaining=_header_integer(
                response.headers, "x-ratelimit-remaining-day", "x-ratelimit-remaining"
            ),
        )
        self.remaining = quota.remaining
        return SearchPage(self.name, records, total, next_cursor, quota)

    def _parse_hit(self, raw: object) -> PaperRecord:
        hit = _mapping(raw)
        source = _mapping(hit.get("source"))
        identifiers = _mapping(hit.get("identifiers"))
        names = _mapping(hit.get("names"))
        links = _mapping(hit.get("links"))
        authors = tuple(
            name
            for item in _list(names.get("authors"))
            if (name := _text(_mapping(item).get("displayName"))) is not None
        )
        citations = sum(
            _integer(_mapping(item).get("count")) or 0 for item in _list(hit.get("citations"))
        )
        return PaperRecord(
            source=self.name,
            source_id=_text(hit.get("uid")) or "",
            wos_uid=_text(hit.get("uid")),
            title=_text(hit.get("title")) or "Untitled",
            doi=_text(identifiers.get("doi")),
            authors=authors,
            journal=_text(source.get("sourceTitle")),
            year=_integer(source.get("publishYear")),
            url=_text(links.get("record")),
            citations=citations,
            raw=dict(hit),
        )


class OpenAlexSource:
    name: SourceName = "openalex"

    def __init__(
        self,
        api_key: str | None,
        transport: JsonTransport,
        *,
        retry: RetryPolicy | None = None,
        rate_gate: RateGate | None = None,
    ) -> None:
        self.api_key = api_key
        self.transport = transport
        self.retry = retry or RetryPolicy()
        self.rate_gate = rate_gate or RateGate(100)
        self.remaining: int | None = None

    def search(self, query: SearchQuery) -> SearchPage:
        if not self.api_key:
            raise SourceError(self.name, "missing_key", "OpenAlex free API Key is not configured")
        if self.remaining is not None and self.remaining <= 0:
            raise SourceError(self.name, "limited", "OpenAlex daily free allowance is exhausted")
        self.rate_gate.wait()
        response = self.retry.get(
            self.transport,
            OPENALEX_URL,
            params=build_openalex_params(query, self.api_key),
        )
        _raise_for_source(self.name, response)
        meta = _mapping(response.data.get("meta"))
        quota = QuotaStatus(
            limit=_header_integer(response.headers, "x-ratelimit-limit"),
            remaining=_header_integer(response.headers, "x-ratelimit-remaining"),
            reset_seconds=_header_integer(response.headers, "x-ratelimit-reset"),
        )
        self.remaining = quota.remaining
        return SearchPage(
            self.name,
            tuple(self._parse_work(work) for work in _list(response.data.get("results"))),
            _integer(meta.get("count")),
            _text(meta.get("next_cursor")),
            quota,
        )

    def _parse_work(self, raw: object) -> PaperRecord:
        work = _mapping(raw)
        authors = tuple(
            name
            for authorship in _list(work.get("authorships"))
            if (name := _text(_mapping(_mapping(authorship).get("author")).get("display_name")))
            is not None
        )
        primary = _mapping(work.get("primary_location"))
        source = _mapping(primary.get("source"))
        return PaperRecord(
            source=self.name,
            source_id=_text(work.get("id")) or "",
            title=_text(work.get("display_name")) or _text(work.get("title")) or "Untitled",
            doi=_text(work.get("doi")),
            authors=authors,
            journal=_text(source.get("display_name")),
            year=_integer(work.get("publication_year")),
            abstract=restore_inverted_abstract(work.get("abstract_inverted_index")),
            url=_text(primary.get("landing_page_url")),
            citations=_integer(work.get("cited_by_count")),
            raw=dict(work),
        )


def strip_markup(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(without_tags).split()) or None


class CrossrefSource:
    name: SourceName = "crossref"

    def __init__(
        self,
        email: str | None,
        transport: JsonTransport,
        *,
        retry: RetryPolicy | None = None,
        rate_gate: RateGate | None = None,
    ) -> None:
        self.email = email
        self.transport = transport
        self.retry = retry or RetryPolicy()
        self.rate_gate = rate_gate or RateGate(10 if email else 5)

    def search(self, query: SearchQuery) -> SearchPage:
        self.rate_gate.wait()
        headers = {"User-Agent": f"CatalystLiterature/0.1 (mailto:{self.email or 'not-set'})"}
        params: dict[str, str | int] = {}
        if self.email:
            params["mailto"] = self.email
        url = CROSSREF_URL
        if query.field == "doi":
            url = f"{CROSSREF_URL}/{quote(query.text.strip(), safe='')}"
        else:
            params["rows"] = query.page_size
            if query.cursor:
                params["cursor"] = query.cursor
            elif query.page > 1:
                params["offset"] = (query.page - 1) * query.page_size
            parameter = {
                "title": "query.title",
                "author": "query.author",
                "topic": "query.bibliographic",
            }[query.field]
            params[parameter] = query.text
        response = self.retry.get(self.transport, url, params=params, headers=headers)
        _raise_for_source(self.name, response)
        message = _mapping(response.data.get("message"))
        total: int | None
        if query.field == "doi":
            items = [message]
            total = 1 if message else 0
            next_cursor = None
        else:
            items = _list(message.get("items"))
            total = _integer(message.get("total-results"))
            next_cursor = (
                _text(message.get("next-cursor")) if len(items) == query.page_size else None
            )
        quota = QuotaStatus(
            limit=_header_integer(response.headers, "x-rate-limit-limit"),
            remaining=None,
        )
        return SearchPage(
            self.name,
            tuple(self._parse_work(item) for item in items),
            total,
            next_cursor,
            quota,
        )

    def _parse_work(self, raw: object) -> PaperRecord:
        work = _mapping(raw)
        titles = _list(work.get("title"))
        journals = _list(work.get("container-title"))
        date_parts = _list(
            _mapping(work.get("published-print") or work.get("published")).get("date-parts")
        )
        first_date = _list(date_parts[0]) if date_parts else []
        doi = _text(work.get("DOI"))
        return PaperRecord(
            source=self.name,
            source_id=doi or _text(work.get("URL")) or "",
            title=(_text(titles[0]) if titles else None) or "Untitled",
            doi=doi,
            authors=tuple(
                " ".join(
                    part
                    for part in (
                        _text(_mapping(author).get("given")),
                        _text(_mapping(author).get("family")),
                    )
                    if part
                )
                for author in _list(work.get("author"))
            ),
            journal=_text(journals[0]) if journals else None,
            year=_integer(first_date[0]) if first_date else None,
            abstract=strip_markup(work.get("abstract")),
            url=_text(work.get("URL")),
            raw=dict(work),
        )
