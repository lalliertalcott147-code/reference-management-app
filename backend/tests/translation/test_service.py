from __future__ import annotations

import threading
import time
from pathlib import Path

from catalyst_literature.config import AppPaths
from catalyst_literature.storage.cache import CacheManager
from catalyst_literature.storage.database import DatabaseManager, require_row, utc_now
from catalyst_literature.storage.jobs import JobRepository
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository
from catalyst_literature.translation.model import ModelManifest
from catalyst_literature.translation.service import (
    GlossaryRepository,
    TranslationCoordinator,
    TranslationService,
)


class FakeEngine:
    def __init__(self) -> None:
        self.calls = 0

    def translate(self, text: str, instruction: str, *, timeout: float) -> str:
        assert "催化领域术语" in instruction
        assert timeout > 0
        self.calls += 1
        return "译:" + text


def setup_service(tmp_path: Path) -> tuple[DatabaseManager, int, FakeEngine, TranslationService]:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    core = manager.require_core()
    paper_id = PaperRepository(core).create(
        PaperDraft("Catalyst at 573 K", doi="10.1000/translate", year=2026)
    )
    core.execute(
        """
        INSERT INTO abstracts(paper_id, language, content, content_hash, is_preferred, created_at)
        VALUES(?, 'en', ?, 'abstract-hash', 1, ?)
        """,
        (paper_id, "NiO showed high conversion at 573 K [12].", utc_now()),
    )
    engine = FakeEngine()
    manifest = ModelManifest(
        "repo", "fake", "https://huggingface.co/repo/fake", 1, "0", "v1", "Apache-2.0"
    )
    service = TranslationService(
        core=core,
        cache=CacheManager(manager.require_cache(), manager.paths.cache),
        engine=engine,
        manifest=manifest,
    )
    return manager, paper_id, engine, service


def test_translation_cache_persistence_and_original_are_independent(tmp_path: Path) -> None:
    manager, paper_id, engine, service = setup_service(tmp_path)
    try:
        cancelled = threading.Event()
        progress: list[tuple[int, int]] = []
        first = service.translate(
            paper_id=paper_id,
            field_name="abstract",
            save=False,
            use_glossary=True,
            cancelled=cancelled,
            progress=lambda a, b: progress.append((a, b)),
        )
        second = service.translate(
            paper_id=paper_id,
            field_name="abstract",
            save=True,
            use_glossary=True,
            cancelled=cancelled,
            progress=lambda _a, _b: None,
        )
        assert engine.calls == 1
        assert first.from_cache is False
        assert second.from_cache is True
        assert "573 K" in second.translated_text
        assert "[12]" in second.translated_text
        assert progress == [(1, 1)]
        core = manager.require_core()
        translation_count = require_row(
            core.execute("SELECT count(*) FROM translations").fetchone(), "count"
        )[0]
        abstract = require_row(
            core.execute("SELECT content FROM abstracts").fetchone(), "abstract"
        )[0]
        assert translation_count == 1
        assert abstract == "NiO showed high conversion at 573 K [12]."
    finally:
        manager.close()


def test_selected_pdf_text_translation_uses_cache_without_overwriting_paper(
    tmp_path: Path,
) -> None:
    manager, paper_id, engine, service = setup_service(tmp_path)
    try:
        first = service.translate_text(
            paper_id=paper_id,
            source_text="Selected catalyst sentence.",
            use_glossary=True,
            cancelled=threading.Event(),
            progress=lambda _current, _total: None,
        )
        second = service.translate_text(
            paper_id=paper_id,
            source_text="Selected catalyst sentence.",
            use_glossary=True,
            cancelled=threading.Event(),
            progress=lambda _current, _total: None,
        )
        assert first.field_name == "selection"
        assert first.translated_text == "译:Selected catalyst sentence."
        assert first.saved is False
        assert second.from_cache is True
        assert engine.calls == 1
        assert require_row(
            manager.require_core()
            .execute("SELECT title_zh FROM papers WHERE id=?", (paper_id,))
            .fetchone(),
            "paper title",
        )[0] is None
        assert require_row(
            manager.require_core().execute("SELECT count(*) FROM translations").fetchone(),
            "translation count",
        )[0] == 0
    finally:
        manager.close()


def test_user_glossary_crud_changes_version(tmp_path: Path) -> None:
    manager, _paper_id, _engine, _service = setup_service(tmp_path)
    try:
        glossary = GlossaryRepository(manager.require_core())
        term_id = glossary.add("oxygen vacancy", "氧空位", "glossary")
        protected_id = glossary.add("ZSM-5", None, "do_not_translate")
        assert glossary.translation_terms()["oxygen vacancy"] == "氧空位"
        assert glossary.protected_terms() == ["ZSM-5"]
        assert {item["id"] for item in glossary.list_user_terms()} == {term_id, protected_id}
        glossary.delete(term_id)
        assert "oxygen vacancy" not in glossary.translation_terms()
    finally:
        manager.close()


class BlockingEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def translate(self, text: str, instruction: str, *, timeout: float) -> str:
        self.started.set()
        self.release.wait(timeout=2)
        return super().translate(text, instruction, timeout=timeout)


def test_translation_queue_can_cancel_without_saving_partial_result(tmp_path: Path) -> None:
    manager, paper_id, _engine, service = setup_service(tmp_path)
    blocking = BlockingEngine()
    service.engine = blocking
    coordinator = TranslationCoordinator(service, JobRepository(manager.require_core()))
    try:
        job_id = coordinator.submit(
            paper_id=paper_id, field_name="abstract", save=True, use_glossary=True
        )
        assert blocking.started.wait(timeout=2)
        assert coordinator.cancel(job_id) is True
        blocking.release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            job = coordinator.get(job_id)
            if job is not None and job.status == "cancelled":
                break
            time.sleep(0.01)
        assert coordinator.get(job_id).status == "cancelled"  # type: ignore[union-attr]
        count = require_row(
            manager.require_core().execute("SELECT count(*) FROM translations").fetchone(),
            "translation count",
        )[0]
        assert count == 0
    finally:
        coordinator.close()
        manager.close()
