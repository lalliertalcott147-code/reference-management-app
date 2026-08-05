from __future__ import annotations

import time
from pathlib import Path

from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.pdfs.processing import PdfProcessingCoordinator
from catalyst_literature.pdfs.wiring import PdfRuntime
from catalyst_literature.security import SESSION_COOKIE, SessionManager
from catalyst_literature.storage.database import DatabaseManager
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository
from fastapi.testclient import TestClient

from .helpers import write_text_pdf
from .test_processing import DirectRunner

ORIGIN = "http://127.0.0.1:43210"


def test_pdf_api_stream_preview_confirm_process_and_manual_metadata(tmp_path: Path) -> None:
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "app"))
    database = DatabaseManager(settings.paths)
    database.initialize()
    paper_id = PaperRepository(database.require_core()).create(PaperDraft("Existing record"))
    pdf = tmp_path / "upload.pdf"
    write_text_pdf(
        pdf,
        [
            "Uploaded Catalyst Study",
            "Ming Li and Alex Smith",
            "2026 DOI 10.1000/upload",
            "Abstract " + "Reliable abstract content. " * 4,
            "Introduction",
        ],
    )
    runtime = PdfRuntime(database, settings.paths)
    runtime.processing.close()
    runtime.processing = PdfProcessingCoordinator(
        database.require_core(), DirectRunner(settings.paths.runtime)
    )
    sessions = SessionManager()
    app = create_app(
        settings,
        origin=ORIGIN,
        sessions=sessions,
        database=database,
        pdf_runtime=runtime,
    )
    headers = {"Origin": ORIGIN}
    try:
        with TestClient(app) as client:
            client.cookies.set(SESSION_COOKIE, sessions.session_token)
            with pdf.open("rb") as source:
                preview = client.post(
                    "/api/pdfs/preview",
                    params={"paper_id": paper_id},
                    files={"file": ("upload.pdf", source, "application/pdf")},
                    headers=headers,
                )
            assert preview.status_code == 200
            payload = preview.json()
            assert payload["page_count"] == 1
            assert payload["preview"]["duplicate_level"] == "none"
            confirmed = client.post(
                "/api/pdfs/confirm",
                json={
                    "upload_token": payload["token"],
                    "paper_id": paper_id,
                    "resolution": "attach",
                },
                headers=headers,
            )
            assert confirmed.status_code == 200
            result = confirmed.json()
            deadline = time.monotonic() + 3
            job = {}
            while time.monotonic() < deadline:
                job = client.get(f"/api/jobs/{result['job_id']}").json()
                if job.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.01)
            assert job["status"] == "completed"
            analysis = client.get(f"/api/pdfs/{result['file_id']}/analysis").json()
            assert analysis["pages"][0]["source"] == "text"
            updated = client.put(
                f"/api/pdfs/{result['file_id']}/metadata",
                json={
                    "paper_id": paper_id,
                    "title": "Confirmed PDF title",
                    "abstract": "Confirmed abstract",
                    "doi": "10.1000/confirmed",
                    "authors": ["Ming Li", "Alex Smith"],
                    "year": 2026,
                },
                headers=headers,
            )
            assert updated.status_code == 200
            detail = client.get(f"/api/papers/{paper_id}").json()
            assert detail["title"] == "Confirmed PDF title"
            assert detail["abstract"] == "Confirmed abstract"
    finally:
        database.close()
