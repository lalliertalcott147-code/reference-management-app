from __future__ import annotations

import hashlib
import json

from .models import SearchQuery

WOS_FIELD_TAGS = {"topic": "TS", "title": "TI", "author": "AU", "doi": "DO"}


def quote_wos(value: str) -> str:
    cleaned = " ".join(value.strip().split()).replace('"', r"\"")
    return f'"{cleaned}"'


def build_wos_query(query: SearchQuery) -> str:
    clauses = [f"{WOS_FIELD_TAGS[query.field]}={quote_wos(query.text)}"]
    if query.year_from or query.year_to:
        start = query.year_from or query.year_to
        end = query.year_to or query.year_from
        clauses.append(f"PY={start}-{end}" if start != end else f"PY={start}")
    return " AND ".join(clauses)


def build_openalex_params(query: SearchQuery, api_key: str) -> dict[str, str | int]:
    params: dict[str, str | int] = {"api_key": api_key, "per_page": min(query.page_size, 50)}
    if query.cursor:
        params["cursor"] = query.cursor
    else:
        params["page"] = query.page
    if query.field == "doi":
        params["filter"] = f"doi:{query.text.strip()}"
    elif query.field == "author":
        params["search"] = query.text
    else:
        params["search"] = query.text
    if query.year_from or query.year_to:
        filters = [] if "filter" not in params else [str(params["filter"])]
        if query.year_from:
            filters.append(f"from_publication_date:{query.year_from}-01-01")
        if query.year_to:
            filters.append(f"to_publication_date:{query.year_to}-12-31")
        params["filter"] = ",".join(filters)
    return params


def query_cache_key(source: str, query: SearchQuery) -> str:
    canonical = json.dumps(
        {"source": source, **query.as_dict()},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
