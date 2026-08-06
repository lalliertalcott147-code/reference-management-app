from __future__ import annotations

from pathlib import Path

from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.lifecycle import LifecycleMonitor
from catalyst_literature.search.cache import SearchCache
from catalyst_literature.search.service import SearchService
from catalyst_literature.security import SESSION_COOKIE, SessionManager
from catalyst_literature.storage.cache import CacheManager
from catalyst_literature.storage.database import DatabaseManager
from fastapi.testclient import TestClient


def make_client(tmp_path: Path) -> tuple[TestClient, SessionManager]:
    sessions = SessionManager()
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "data"))
    app = create_app(
        settings,
        origin="http://127.0.0.1:43210",
        sessions=sessions,
        lifecycle=LifecycleMonitor(),
    )
    return TestClient(app), sessions


def test_health_is_public_but_session_api_is_not(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["cache-control"] == "no-store"
    assert "object-src 'none'" in health.headers["content-security-policy"]
    assert client.get("/api/session").status_code == 401


def test_launch_token_is_one_time_and_sets_http_only_cookie(tmp_path: Path) -> None:
    client, sessions = make_client(tmp_path)
    response = client.get(
        "/launch", params={"token": sessions.launch_token}, follow_redirects=False
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert client.get("/launch", params={"token": sessions.launch_token}).status_code == 401


def test_write_requires_valid_origin_even_with_session(tmp_path: Path) -> None:
    client, sessions = make_client(tmp_path)
    client.cookies.set(SESSION_COOKIE, sessions.session_token)
    payload = {"tab_id": "tab_1"}
    assert client.post("/api/lifecycle/heartbeat", json=payload).status_code == 403
    assert (
        client.post(
            "/api/lifecycle/heartbeat",
            json=payload,
            headers={"Origin": "http://evil.example"},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/lifecycle/heartbeat",
        json=payload,
        headers={"Origin": "http://127.0.0.1:43210"},
    )
    assert response.status_code == 200
    assert response.json()["active_tabs"] == 1


def test_invalid_tab_identifier_is_rejected(tmp_path: Path) -> None:
    client, sessions = make_client(tmp_path)
    client.cookies.set(SESSION_COOKIE, sessions.session_token)
    response = client.post(
        "/api/lifecycle/heartbeat",
        json={"tab_id": "spaces are not allowed"},
        headers={"Origin": "http://127.0.0.1:43210"},
    )
    assert response.status_code == 422


def test_search_endpoint_uses_authenticated_local_service(tmp_path: Path) -> None:
    sessions = SessionManager()
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "data"))
    database = DatabaseManager(settings.paths)
    database.initialize()
    service = SearchService(
        (),
        SearchCache(CacheManager(database.require_cache(), database.paths.cache)),
    )
    app = create_app(
        settings,
        origin="http://127.0.0.1:43210",
        sessions=sessions,
        database=database,
        search_service=service,
    )
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, sessions.session_token)
    try:
        response = client.post(
            "/api/search",
            json={"text": "photocatalysis", "field": "topic"},
            headers={"Origin": "http://127.0.0.1:43210"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "papers": [],
            "statuses": [],
            "recognized_queries": ["photocatalysis"],
        }
    finally:
        database.close()
