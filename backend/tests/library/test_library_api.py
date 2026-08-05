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
        second_library = client.post(
            "/api/libraries", json={"name": "PDF Collection"}, headers=headers
        ).json()["id"]
        assigned = client.post(
            f"/api/libraries/{second_library}/papers",
            json={"paper_id": paper_id},
            headers=headers,
        )
        assert assigned.json() == {"added": True}
        duplicate_assignment = client.post(
            f"/api/libraries/{second_library}/papers",
            json={"paper_id": paper_id},
            headers=headers,
        )
        assert duplicate_assignment.json() == {"added": False}
        assert [item["id"] for item in client.get(
            "/api/library/papers", params={"library_id": second_library}
        ).json()] == [paper_id]
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
        all_workspace = client.get("/api/library/workspace")
        assert all_workspace.status_code == 200
        assert all_workspace.json()["library_id"] is None
        all_saved = client.put(
            "/api/library/workspace",
            json={
                "body": "all-papers synthesis",
                "note_x": 25,
                "note_y": 35,
                "note_width": 560,
                "note_height": 300,
            },
            headers=headers,
        )
        assert all_saved.json()["version"] == 2
        all_card = client.post(
            "/api/library/workspace/cards",
            json={"paper_id": paper_id},
            headers=headers,
        )
        assert all_card.status_code == 200
        text_element = client.post(
            "/api/library/workspace/elements",
            json={
                "element_type": "text",
                "x": 180,
                "y": 440,
                "width": 280,
                "height": 140,
                "content": "canvas conclusion",
                "color": "#315f59",
            },
            headers=headers,
        )
        assert text_element.status_code == 200
        element_id = text_element.json()["id"]
        moved_element = client.put(
            f"/api/library-workspace/elements/{element_id}",
            json={
                "element_type": "text",
                "x": 260,
                "y": 520,
                "width": 300,
                "height": 160,
                "content": "updated canvas conclusion",
                "color": "#224466",
            },
            headers=headers,
        )
        assert moved_element.json() == {"updated": True}
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
        refreshed_all = client.get("/api/library/workspace").json()
        assert refreshed_all["body"] == "all-papers synthesis"
        assert refreshed_all["cards"][0]["paper_id"] == paper_id
        assert refreshed_all["elements"][0]["content"] == "updated canvas conclusion"
        deleted_element = client.delete(
            f"/api/library-workspace/elements/{element_id}", headers=headers
        )
        assert deleted_element.json() == {"deleted": True}
        assert client.get("/api/library/workspace").json()["elements"] == []
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
        assert [item["id"] for item in client.get("/api/libraries").json()] == [
            second_library
        ]
        restored = client.post(f"/api/libraries/{library_id}/restore", headers=headers)
        assert restored.status_code == 200
        assert {item["name"] for item in client.get("/api/libraries").json()} == {
            "API Project",
            "PDF Collection",
        }
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
