from __future__ import annotations

import base64
from pathlib import Path

from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.security import SESSION_COOKIE, SessionManager
from catalyst_literature.storage.database import DatabaseManager, require_row
from fastapi.testclient import TestClient

ORIGIN = "http://127.0.0.1:43210"
ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def authenticated_app(tmp_path: Path) -> tuple[TestClient, DatabaseManager]:
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "app"))
    database = DatabaseManager(settings.paths)
    database.initialize()
    sessions = SessionManager()
    app = create_app(settings, origin=ORIGIN, sessions=sessions, database=database)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, sessions.session_token)
    return client, database


def test_settings_api_masks_dpapi_keys_and_persists_preferences(tmp_path: Path) -> None:
    client, database = authenticated_app(tmp_path)
    try:
        response = client.put(
            "/api/settings",
            json={
                "wos_api_key": "wos-super-secret-1234",
                "openalex_api_key": "openalex-secret-5678",
                "crossref_email": "researcher@example.edu",
                "personalization_enabled": False,
                "onboarding_complete": True,
            },
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["wos_api_key"] == "****1234"
        assert payload["openalex_api_key"] == "****5678"
        assert payload["crossref_email"] == "researcher@example.edu"
        assert payload["personalization_enabled"] is False
        database.checkpoint()
        raw = database.core_path.read_bytes()
        assert b"wos-super-secret-1234" not in raw
        assert b"openalex-secret-5678" not in raw
    finally:
        database.close()


def test_avatar_upload_validates_and_persists_local_image(tmp_path: Path) -> None:
    client, database = authenticated_app(tmp_path)
    try:
        invalid = client.post(
            "/api/profile/avatar",
            files={"file": ("avatar.svg", b"<svg></svg>", "image/svg+xml")},
            headers={"Origin": ORIGIN},
        )
        assert invalid.status_code == 422

        uploaded = client.post(
            "/api/profile/avatar",
            files={"file": ("avatar.png", ONE_PIXEL_PNG, "image/png")},
            headers={"Origin": ORIGIN},
        )
        assert uploaded.status_code == 200
        avatar_url = uploaded.json()["avatar_url"]
        assert avatar_url.startswith("/api/profile/avatar?v=")
        assert (database.paths.root / "profile" / "avatar.png").read_bytes() == ONE_PIXEL_PNG

        downloaded = client.get(avatar_url)
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"] == "image/png"
        assert downloaded.content == ONE_PIXEL_PNG
        assert client.get("/api/settings").json()["avatar_url"] == avatar_url
    finally:
        database.close()


def test_display_name_is_user_configurable_and_persistent(tmp_path: Path) -> None:
    client, database = authenticated_app(tmp_path)
    try:
        assert client.get("/api/settings").json()["display_name"] == "研究者"
        updated = client.put(
            "/api/settings",
            json={"display_name": "  Zyyyy   Researcher  "},
            headers={"Origin": ORIGIN},
        )
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "Zyyyy Researcher"
        assert client.get("/api/settings").json()["display_name"] == "Zyyyy Researcher"

        blank = client.put(
            "/api/settings",
            json={"display_name": "   "},
            headers={"Origin": ORIGIN},
        )
        assert blank.status_code == 422
        assert client.get("/api/settings").json()["display_name"] == "Zyyyy Researcher"
    finally:
        database.close()


def test_save_paper_state_library_and_detail_are_idempotent(tmp_path: Path) -> None:
    client, database = authenticated_app(tmp_path)
    request = {
        "liked": True,
        "saved": True,
        "reading_status": "reading",
        "sources": [
            {
                "source": "wos",
                "source_id": "WOS:1",
                "wos_uid": "WOS:1",
                "title": "Catalyst paper",
                "doi": "10.1000/test",
                "authors": ["Ming Li"],
                "journal": "Catalysis Journal",
                "year": 2026,
                "citations": 4,
            },
            {
                "source": "openalex",
                "source_id": "W1",
                "title": "Catalyst paper",
                "doi": "https://doi.org/10.1000/test",
                "authors": ["Ming Li"],
                "journal": "Catalysis Journal",
                "year": 2026,
                "abstract": "An open abstract",
            },
        ],
    }
    try:
        first = client.post("/api/papers/save", json=request, headers={"Origin": ORIGIN})
        second = client.post("/api/papers/save", json=request, headers={"Origin": ORIGIN})
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["paper_id"] == second.json()["paper_id"]
        paper_id = first.json()["paper_id"]
        detail = client.get(f"/api/papers/{paper_id}")
        assert detail.status_code == 200
        assert detail.json()["liked"] is True
        assert detail.json()["reading_status"] == "reading"
        assert detail.json()["abstract"] == "An open abstract"
        assert len(detail.json()["sources"]) == 2
        core = database.require_core()
        assert require_row(core.execute("SELECT count(*) FROM papers").fetchone(), "count")[0] == 1
        assert require_row(
            core.execute("SELECT count(*) FROM library_papers").fetchone(), "count"
        )[0] == 1
    finally:
        database.close()
