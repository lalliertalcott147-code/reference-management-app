from __future__ import annotations

from pathlib import Path

from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.search.merge import merge_records
from catalyst_literature.search.models import PaperRecord, SearchQuery, SourceStatus
from catalyst_literature.search.service import CombinedSearchResult
from catalyst_literature.security import SESSION_COOKIE, SessionManager
from catalyst_literature.storage.database import DatabaseManager
from fastapi.testclient import TestClient

ORIGIN = "http://127.0.0.1:43210"


class ApiSearchService:
    def search(self, _query: SearchQuery, *, refresh: bool = False) -> CombinedSearchResult:
        record = PaperRecord(
            source="crossref",
            source_id="api-update",
            title="Catalysis API update",
            doi="10.1000/api-update",
            authors=("Ada Chen",),
            journal="Catalysis Today",
            year=2026,
            abstract="photocatalysis result",
        )
        return CombinedSearchResult(
            tuple(merge_records([record])),
            (SourceStatus("crossref", "success", "fixture"),),
        )


def test_preferences_saved_search_journal_alert_and_settings_api(tmp_path: Path) -> None:
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "app"))
    database = DatabaseManager(settings.paths)
    database.initialize()
    sessions = SessionManager()
    app = create_app(
        settings,
        origin=ORIGIN,
        sessions=sessions,
        database=database,
        search_service=ApiSearchService(),  # type: ignore[arg-type]
    )
    headers = {"Origin": ORIGIN}
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, sessions.session_token)
        topic = client.post(
            "/api/preferences/topics",
            json={"name": "光催化", "query_text": "photocatalysis", "enabled": True},
            headers=headers,
        )
        assert topic.status_code == 200
        assert client.get("/api/preferences/topics").json()[0]["name"] == "光催化"
        term = client.post(
            "/api/preferences/interest-terms",
            json={
                "term": "转化率",
                "mapped_term": "conversion",
                "term_type": "positive",
            },
            headers=headers,
        )
        assert term.status_code == 200
        listed_terms = client.get("/api/preferences/interest-terms").json()
        assert listed_terms[0]["term"] == "转化率"
        assert listed_terms[0]["mapped_term"] == "conversion"

        saved = client.post(
            "/api/saved-searches",
            json={"name": "每日电催化", "text": "electrocatalysis"},
            headers=headers,
        )
        saved_id = saved.json()["id"]
        run_saved = client.post(
            f"/api/saved-searches/{saved_id}/run", headers=headers
        )
        assert run_saved.json() == {"new_count": 1}

        journal = client.post(
            "/api/journals/subscriptions",
            json={"title": "Catalysis Today"},
            headers=headers,
        )
        journal_id = journal.json()["id"]
        run_journal = client.post(
            f"/api/journals/subscriptions/{journal_id}/run", headers=headers
        )
        assert run_journal.json() == {"new_count": 1}
        journal_papers = client.get(
            f"/api/journals/subscriptions/{journal_id}/papers"
        )
        assert journal_papers.status_code == 200
        assert journal_papers.json()[0]["title"] == "Catalysis API update"
        assert journal_papers.json()[0]["abstract"] == "photocatalysis result"
        assert client.get("/api/recommendations").json()[0]["reasons"]

        alerts = client.get("/api/alerts").json()
        assert {alert["kind"] for alert in alerts} == {"saved_search", "journal"}
        assert client.post("/api/alerts/read", headers=headers).status_code == 200
        assert client.get("/api/alerts?unread_only=true").json() == []

        response = client.put(
            "/api/settings",
            json={"automatic_search_daily_limit": 7},
            headers=headers,
        )
        assert response.json()["automatic_search_daily_limit"] == 7
    database.close()
