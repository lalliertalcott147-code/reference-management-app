from __future__ import annotations

import json
from pathlib import Path

from catalyst_literature.config import AppPaths
from catalyst_literature.search.cache import SearchCache
from catalyst_literature.search.merge import merge_records
from catalyst_literature.search.models import (
    PaperRecord,
    SearchPage,
    SearchQuery,
    SourceError,
)
from catalyst_literature.search.persistence import SearchResultRepository
from catalyst_literature.search.service import SearchService
from catalyst_literature.storage.cache import CacheManager
from catalyst_literature.storage.database import DatabaseManager, require_row


class StubSource:
    def __init__(self, page: SearchPage | SourceError) -> None:
        self.page = page
        self.name = page.source

    def search(self, query: SearchQuery) -> SearchPage:
        del query
        if isinstance(self.page, SourceError):
            raise self.page
        return self.page


def records() -> list[PaperRecord]:
    return [
        PaperRecord(
            "wos",
            "WOS:1",
            "Canonical catalyst title",
            doi="10.1000/Test",
            wos_uid="WOS:1",
            authors=("Li, M",),
            journal="Catalysis Journal",
            year=2026,
            citations=8,
        ),
        PaperRecord(
            "openalex",
            "W1",
            "Canonical catalyst title",
            doi="https://doi.org/10.1000/test",
            authors=("Ming Li",),
            journal="Catalysis Journal",
            year=2026,
            abstract="Open abstract",
        ),
        PaperRecord(
            "crossref",
            "10.1000/test",
            "Alternative deposited title",
            doi="10.1000/test",
            authors=("Ming Li",),
            year=2026,
            abstract="Deposited abstract",
        ),
    ]


def test_merge_uses_field_priority_and_preserves_conflicting_values() -> None:
    merged = merge_records(records())
    assert len(merged) == 1
    paper = merged[0]
    assert paper.doi == "10.1000/test"
    assert paper.title == "Canonical catalyst title"
    assert paper.abstract == "Open abstract"
    assert [item.value for item in paper.provenance["title"]] == [
        "Canonical catalyst title",
        "Alternative deposited title",
    ]
    assert paper.provenance["abstract"][1].source == "crossref"


def test_conflicting_dois_are_not_silently_weak_merged() -> None:
    two = [
        PaperRecord("openalex", "1", "Same title", doi="10.1/a", year=2026),
        PaperRecord("crossref", "2", "Same title", doi="10.1/b", year=2026),
    ]
    assert len(merge_records(two)) == 2


def test_search_cache_offline_refresh_and_failure_isolation(tmp_path: Path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    cache = SearchCache(
        CacheManager(
            manager.require_cache(),
            manager.paths.cache,
            target_bytes=50_000,
            hard_limit_bytes=60_000,
        )
    )
    query = SearchQuery("catalyst")
    wos_page = SearchPage("wos", (records()[0],), 1)
    openalex_failure = SourceError("openalex", "limited", "free allowance exhausted")
    service = SearchService((StubSource(wos_page), StubSource(openalex_failure)), cache)
    try:
        first = service.search(query)
        assert first.statuses[0].state == "success"
        assert first.statuses[1].state == "limited"
        offline = service.search(query, online=False)
        assert offline.statuses[0].state == "cache"
        assert offline.statuses[1].state == "offline"
        refreshed = service.search(query, refresh=True)
        assert refreshed.statuses[0].state == "success"
    finally:
        manager.close()


def test_saved_merge_is_idempotent_and_survives_restart_with_provenance(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "app")
    manager = DatabaseManager(paths)
    manager.initialize()
    paper = merge_records(records())[0]
    repository = SearchResultRepository(manager.require_core())
    first_id = repository.save(paper)
    second_id = repository.save(paper)
    assert first_id == second_id
    manager.close()

    reopened = DatabaseManager(paths)
    reopened.initialize()
    try:
        core = reopened.require_core()
        assert require_row(core.execute("SELECT count(*) FROM papers").fetchone(), "count")[0] == 1
        assert (
            require_row(core.execute("SELECT count(*) FROM paper_sources").fetchone(), "count")[0]
            == 3
        )
        assert (
            require_row(core.execute("SELECT count(*) FROM abstracts").fetchone(), "count")[0] == 2
        )
        raw = str(
            require_row(
                core.execute(
                    "SELECT raw_summary_json FROM paper_sources WHERE source='crossref'"
                ).fetchone(),
                "source summary",
            )[0]
        )
        assert json.loads(raw)["title"] == "Alternative deposited title"
        assert (
            require_row(
                core.execute(
                    "SELECT count(*) FROM paper_fts WHERE paper_fts MATCH 'catalyst'"
                ).fetchone(),
                "fts result",
            )[0]
            == 1
        )
    finally:
        reopened.close()
