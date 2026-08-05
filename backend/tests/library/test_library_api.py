from __future__ import annotations

from pathlib import Path

from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.library import LibraryService
from catalyst_literature.security import SESSION_COOKIE, SessionManager
from catalyst_literature.storage.database import DatabaseManager, require_row
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository
from fastapi.testclient import TestClient

ORIGIN = "http://127.0.0.1:43210"


def test_library_api_crud_notes_tags_search_export_and_trash(tmp_path: Path) -> None:
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "app"))
    database = DatabaseManager(settings.paths)
    database.initialize()
    paper_id = PaperRepository(database.require_core()).create(
        PaperDraft("Copper catalyst", doi="10.1000/api", year=2026)
    )
    service = LibraryService(database.require_core(), database.paths)
    library_id = service.create_library("API Project")
    service.add_paper(library_id, paper_id)
    sessions = SessionManager()
    app = create_app(settings, origin=ORIGIN, sessions=sessions, database=database)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, sessions.session_token)
    headers = {"Origin": ORIGIN}
    try:
        libraries = client.get("/api/libraries")
        assert libraries.status_code == 200
        assert libraries.json()[0]["paper_count"] == 1
        state = client.put(
            f"/api/papers/{paper_id}/state",
            json={"liked": True, "saved": True, "reading_status": "read"},
            headers=headers,
        )
        assert state.status_code == 200
        note = client.post(
            "/api/notes",
            json={"paper_id": paper_id, "body": "kinetics insight", "library_id": library_id},
            headers=headers,
        )
        assert note.json()["version"] == 1
        appended = client.post(
            "/api/notes/append",
            json={"paper_id": paper_id, "body": "PDF translated excerpt", "library_id": library_id},
            headers=headers,
        )
        assert appended.json()["version"] == 2
        workspace = client.get(f"/api/libraries/{library_id}/workspace")
        assert workspace.status_code == 200
        assert workspace.json()["cards"] == []
        saved_workspace = client.put(
            f"/api/libraries/{library_id}/workspace",
            json={
                "body": "global synthesis",
                "note_x": 30,
                "note_y": 40,
                "note_width": 540,
                "note_height": 280,
            },
            headers=headers,
        )
        assert saved_workspace.json()["version"] == 2
        card = client.post(
            f"/api/libraries/{library_id}/workspace/cards",
            json={"paper_id": paper_id},
            headers=headers,
        )
        assert card.status_code == 200
        card_id = card.json()["id"]
        moved = client.put(
            f"/api/library-workspace/cards/{card_id}",
            json={"x": 700, "y": 80, "width": 340, "height": 360},
            headers=headers,
        )
        assert moved.json() == {"updated": True}
        refreshed_workspace = client.get(f"/api/libraries/{library_id}/workspace").json()
        assert refreshed_workspace["body"] == "global synthesis"
        assert refreshed_workspace["cards"][0]["x"] == 700.0
        assert "PDF translated excerpt" in refreshed_workspace["cards"][0]["notes"][0]["body"]
        tag = client.post(
            "/api/tags",
            json={"name": "kinetics", "paper_ids": [paper_id], "library_id": library_id},
            headers=headers,
        )
        assert tag.status_code == 200
        search = client.get("/api/library/papers", params={"q": "kinetics"})
        assert [item["id"] for item in search.json()] == [paper_id]
        export = client.post(
            "/api/library/export",
            json={"paper_ids": [paper_id], "format": "ris"},
            headers=headers,
        )
        assert export.status_code == 200
        assert "Copper catalyst" in export.text
        assert "papers.ris" in export.headers["content-disposition"]
        deleted = client.delete(f"/api/libraries/{library_id}", headers=headers)
        assert deleted.status_code == 200
        assert client.get("/api/libraries").json() == []
        restored = client.post(f"/api/libraries/{library_id}/restore", headers=headers)
        assert restored.status_code == 200
        assert client.get("/api/libraries").json()[0]["name"] == "API Project"
        assert (
            require_row(
                database.require_core()
                .execute("SELECT count(*) FROM paper_note_versions")
                .fetchone(),
                "note version count",
            )[0]
            == 2
        )
    finally:
        database.close()
