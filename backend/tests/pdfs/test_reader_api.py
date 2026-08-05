from __future__ import annotations

from pathlib import Path

from catalyst_literature.app import create_app
from catalyst_literature.config import AppSettings
from catalyst_literature.security import SESSION_COOKIE, SessionManager
from fastapi.testclient import TestClient

from .test_reader import setup_reader

ORIGIN = "http://127.0.0.1:43210"


def test_reader_api_only_exposes_authorized_file_ids_and_annotation_crud(
    tmp_path: Path,
) -> None:
    manager, _service, paper_id, file_id, _path, digest = setup_reader(tmp_path)
    settings = AppSettings(paths=manager.paths)
    sessions = SessionManager()
    app = create_app(settings, origin=ORIGIN, sessions=sessions, database=manager)
    headers = {"Origin": ORIGIN}
    try:
        with TestClient(app) as client:
            client.cookies.set(SESSION_COOKIE, sessions.session_token)
            content = client.get(f"/api/pdfs/{file_id}/content")
            assert content.status_code == 200
            assert content.content.startswith(b"%PDF-")
            assert content.headers["etag"] == f'"{digest}"'
            assert client.get("/api/pdfs/999999/content").status_code == 404
            assert client.get(f"/api/papers/{paper_id}/pdfs").json()[0]["file_id"] == file_id
            position = client.put(
                f"/api/pdfs/{file_id}/position",
                json={"paper_id": paper_id, "page_number": 1, "scale": 1.2, "scroll_offset": 30},
                headers=headers,
            )
            assert position.status_code == 200
            assert client.get(
                f"/api/pdfs/{file_id}/position", params={"paper_id": paper_id}
            ).json()["scale"] == 1.2
            annotation = client.post(
                f"/api/pdfs/{file_id}/annotations",
                json={
                    "paper_id": paper_id,
                    "annotation_type": "highlight",
                    "page_number": 1,
                    "color": "#F4D35E",
                    "selected_text": "catalyst sentence",
                    "prefix_text": "before",
                    "suffix_text": "after",
                    "rects": [{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.05}],
                    "comment_text": "note",
                },
                headers=headers,
            )
            assert annotation.status_code == 200
            annotation_id = annotation.json()["id"]
            listing = client.get(
                f"/api/pdfs/{file_id}/annotations", params={"paper_id": paper_id}
            ).json()
            assert listing[0]["selected_text"] == "catalyst sentence"
            assert client.put(
                f"/api/pdf-annotations/{annotation_id}",
                json={"comment_text": "edited"},
                headers=headers,
            ).status_code == 200
            assert client.delete(
                f"/api/pdf-annotations/{annotation_id}", headers=headers
            ).status_code == 200
    finally:
        manager.close()
