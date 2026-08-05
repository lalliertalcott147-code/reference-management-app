from __future__ import annotations

from datetime import UTC, datetime, timedelta

from catalyst_literature.config import AppPaths
from catalyst_literature.search.merge import merge_records
from catalyst_literature.search.models import PaperRecord, SearchQuery, SourceStatus
from catalyst_literature.search.service import CombinedSearchResult
from catalyst_literature.storage.database import DatabaseManager
from catalyst_literature.storage.repositories import SettingsRepository
from catalyst_literature.updates import AlertService, UpdateService


class FakeSearchService:
    def __init__(self, batches: list[list[PaperRecord]]) -> None:
        self.batches = batches
        self.calls = 0

    def search(self, _query: SearchQuery, *, refresh: bool = False) -> CombinedSearchResult:
        assert refresh
        index = min(self.calls, len(self.batches) - 1)
        self.calls += 1
        return CombinedSearchResult(
            tuple(merge_records(self.batches[index])),
            (SourceStatus("crossref", "success", "fixture"),),
        )


def record(source_id: str, title: str, journal: str = "Catalysis Today") -> PaperRecord:
    return PaperRecord(
        source="crossref",
        source_id=source_id,
        title=title,
        doi=f"10.1000/{source_id}",
        authors=("Researcher",),
        journal=journal,
        year=2026,
        abstract=f"Abstract for {title}",
    )


def test_saved_search_tracks_only_new_results_and_deduplicates_alerts(tmp_path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "data"))
    manager.initialize()
    first = [record("one", "First catalyst"), record("two", "Second catalyst")]
    second = [*first, record("three", "Third catalyst")]
    fake = FakeSearchService([first, first, second])
    service = UpdateService(manager.require_core(), fake)  # type: ignore[arg-type]
    saved_id = service.save_search("催化更新", SearchQuery("catalysis"))

    assert service.run_saved_search(saved_id) == 2
    assert service.run_saved_search(saved_id) == 0
    assert service.run_saved_search(saved_id) == 1
    saved = service.list_saved_searches()[0]
    assert saved["last_new_count"] == 1
    alerts = AlertService(manager.require_core()).list()
    assert len(alerts) == 2
    assert all(alert["kind"] == "saved_search" for alert in alerts)
    assert manager.require_core().execute("SELECT count(*) FROM papers").fetchone()[0] == 3
    manager.close()


def test_journal_check_filters_other_journals_and_can_be_disabled(tmp_path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "data"))
    manager.initialize()
    fake = FakeSearchService(
        [[record("match", "Matching", "Catalysis Today"), record("other", "Other", "Nature")]]
    )
    service = UpdateService(manager.require_core(), fake)  # type: ignore[arg-type]
    subscription_id = service.follow_journal("Catalysis Today")
    assert service.run_journal(subscription_id) == 1
    assert service.list_journals()[0]["last_match_count"] == 1
    papers = service.list_journal_papers(subscription_id)
    assert len(papers) == 1
    assert papers[0]["title"] == "Matching"
    assert papers[0]["journal"] == "Catalysis Today"
    assert papers[0]["year"] == 2026
    assert papers[0]["abstract"] == "Abstract for Matching"
    service.set_journal_enabled(subscription_id, False)
    assert service.list_journals()[0]["enabled"] is False
    manager.close()


def test_scheduler_runs_only_due_items_and_enforces_daily_limit(tmp_path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "data"))
    manager.initialize()
    fake = FakeSearchService([[record("one", "One")]])
    service = UpdateService(manager.require_core(), fake)  # type: ignore[arg-type]
    service.save_search("one", SearchQuery("one"))
    service.save_search("two", SearchQuery("two"))
    SettingsRepository(manager.require_core()).set("automatic_search_daily_limit", 1)
    now = datetime.now(UTC) + timedelta(seconds=1)

    assert service.run_due(now=now) == 1
    assert fake.calls == 1
    alerts = AlertService(manager.require_core()).list()
    assert any(alert["kind"] == "quota" for alert in alerts)
    manager.close()
