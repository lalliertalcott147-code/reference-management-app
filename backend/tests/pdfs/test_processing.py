from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from catalyst_literature.config import AppPaths
from catalyst_literature.pdfs.analysis import analyze_pdf
from catalyst_literature.pdfs.processing import (
    PdfProcessingCoordinator,
    PdfWorkerRunner,
    _worker_command,
)
from catalyst_literature.storage.database import DatabaseManager, require_row
from catalyst_literature.storage.files import FileRepository

from .helpers import write_text_pdf


class DirectRunner:
    def __init__(self, runtime: Path) -> None:
        self.runtime = runtime

    def run(
        self,
        path: Path,
        job_id: int,
        cancelled: threading.Event,
        progress: Callable[[int, int], None],
    ) -> dict[str, object]:
        del job_id
        if cancelled.is_set():
            raise InterruptedError
        return analyze_pdf(
            path,
            self.runtime,
            ocr=lambda _image, _home: ("OCR", [], 0.8),
            progress=progress,
        )


def test_processing_persists_per_page_source_and_candidates(tmp_path: Path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    pdf = manager.paths.library / "pdfs" / "test.pdf"
    data = write_text_pdf(pdf, ["Catalyst Paper", "Ming Li", "2026 DOI 10.1000/process"])
    file_id = FileRepository(manager.require_core(), manager.paths.library).register(
        sha256=__import__("hashlib").sha256(data).hexdigest(),
        relative_path="pdfs/test.pdf",
        original_name="test.pdf",
        size_bytes=len(data),
        page_count=1,
    )
    coordinator = PdfProcessingCoordinator(
        manager.require_core(), DirectRunner(manager.paths.runtime)
    )
    try:
        job_id = coordinator.submit(file_id, pdf)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = coordinator.jobs.get(job_id)
            if job is not None and job.status in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert coordinator.jobs.get(job_id).status == "completed"  # type: ignore[union-attr]
        assert coordinator.jobs.get(job_id).progress_current == 1  # type: ignore[union-attr]
        core = manager.require_core()
        page = require_row(
            core.execute(
                "SELECT classification, text_source, content FROM pdf_pages WHERE file_id=?",
                (file_id,),
            ).fetchone(),
            "PDF page",
        )
        assert page[0:2] == ("text", "text")
        assert "Catalyst Paper" in page[2]
        assert require_row(
            core.execute(
                "SELECT count(*) FROM pdf_metadata_candidates WHERE file_id=?", (file_id,)
            ).fetchone(),
            "candidate count",
        )[0] >= 2
    finally:
        coordinator.close()
        manager.close()


def test_isolated_pdf_worker_returns_json_without_touching_database(tmp_path: Path) -> None:
    pdf = tmp_path / "isolated.pdf"
    write_text_pdf(pdf, ["Isolated Catalyst", "Worker Author", "2026 DOI 10.1000/worker"])
    runner = PdfWorkerRunner(tmp_path / "runtime")
    (tmp_path / "runtime").mkdir()
    result = runner.run(pdf, 91, threading.Event(), lambda _current, _total: None)
    pages = result["pages"]
    assert isinstance(pages, list)
    assert pages[0]["source"] == "text"


def test_isolated_pdf_inspection_and_frozen_worker_command(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "inspection.pdf"
    write_text_pdf(pdf, ["Inspection Catalyst", "Worker Author", "2026"])
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    page_count, candidates = PdfWorkerRunner(runtime).inspect(pdf)
    assert page_count == 1
    assert any(candidate["field_name"] == "title" for candidate in candidates)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _worker_command(["--mode", "inspect"]) == [
        sys.executable,
        "--pdf-worker",
        "--mode",
        "inspect",
    ]
