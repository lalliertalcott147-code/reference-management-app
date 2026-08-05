from __future__ import annotations

import time
from pathlib import Path

from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.security import SESSION_COOKIE, SessionManager
from catalyst_literature.storage.database import DatabaseManager
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository
from catalyst_literature.translation.wiring import TranslationRuntime
from fastapi.testclient import TestClient

ORIGIN = "http://127.0.0.1:43210"


class ApiEngine:
    def translate(self, text: str, instruction: str, *, timeout: float) -> str:
        del instruction, timeout
        return "中文:" + text


def test_translation_api_jobs_glossary_and_saved_detail(tmp_path: Path) -> None:
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "app"))
    database = DatabaseManager(settings.paths)
    database.initialize()
    paper_id = PaperRepository(database.require_core()).create(PaperDraft("Catalyst design"))
    sessions = SessionManager()
    runtime = TranslationRuntime(database=database, paths=settings.paths)
    runtime.coordinator.service.engine = ApiEngine()
    app = create_app(
        settings,
        origin=ORIGIN,
        sessions=sessions,
        database=database,
        translation_runtime=runtime,
    )
    headers = {"Origin": ORIGIN}
    try:
        with TestClient(app) as client:
            client.cookies.set(SESSION_COOKIE, sessions.session_token)
            model = client.get("/api/translation/model")
            assert model.status_code == 200
            assert model.json()["state"] == "missing"
            denied = client.post(
                "/api/translation/model/download",
                json={"confirmed": False},
                headers=headers,
            )
            assert denied.status_code == 422

            term = client.post(
                "/api/translation/glossary",
                json={
                    "term": "oxygen vacancy",
                    "mapped_term": "氧空位",
                    "term_type": "glossary",
                },
                headers=headers,
            )
            assert term.status_code == 200
            assert client.get("/api/translation/glossary").json()[0]["term"] == "oxygen vacancy"

            created = client.post(
                "/api/translation/jobs",
                json={"paper_id": paper_id, "field_name": "title", "save": True},
                headers=headers,
            )
            assert created.status_code == 200
            job_id = created.json()["job_id"]
            deadline = time.monotonic() + 2
            payload: dict[str, object] = {}
            while time.monotonic() < deadline:
                payload = client.get(f"/api/jobs/{job_id}").json()
                if payload.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.01)
            assert payload["status"] == "completed"
            result = payload["result"]
            assert isinstance(result, dict)
            assert result["translated_text"] == "中文:Catalyst design"
            detail = client.get(f"/api/papers/{paper_id}").json()
            assert detail["title"] == "Catalyst design"
            assert detail["title_zh"] == "中文:Catalyst design"
            assert detail["translations"][0]["translated_text"] == "中文:Catalyst design"
    finally:
        database.close()
