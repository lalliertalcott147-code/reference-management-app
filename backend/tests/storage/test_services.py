from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import apsw
import pytest
from catalyst_literature.config import AppPaths
from catalyst_literature.logging_setup import configure_logging, diagnostic_manifest
from catalyst_literature.storage.backup import create_core_backup, restore_core_backup
from catalyst_literature.storage.cache import CacheManager
from catalyst_literature.storage.database import DatabaseManager, StorageError, require_row, utc_now
from catalyst_literature.storage.files import FileRepository
from catalyst_literature.storage.jobs import JobRepository
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository, SettingsRepository
from catalyst_literature.storage.secrets import SecretStore


def manager_for(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    return manager


def test_dpapi_secret_round_trip_and_database_contains_no_plaintext(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    secret = "wos-live-key-super-secret-9876"
    try:
        store = SecretStore(manager.require_core())
        store.save("wos", secret)
        assert store.read("wos") == secret
        assert store.masked("wos") == "****9876"
        manager.checkpoint()
        assert secret.encode() not in manager.core_path.read_bytes()
    finally:
        manager.close()


def test_jobs_are_idempotent_and_interrupted_work_recovers(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    try:
        jobs = JobRepository(manager.require_core())
        first = jobs.create("translation", "same-request", {"paper_id": 1})
        assert jobs.create("translation", "same-request", {"paper_id": 2}) == first
        jobs.set_status(first, "running")
        assert jobs.recover_interrupted() == (1, 0)
        recovered = jobs.get(first)
        assert recovered is not None
        assert recovered.status == "pending"
        assert recovered.retry_count == 1
        manager.require_core().execute(
            "UPDATE jobs SET status='running', retry_count=3 WHERE id=?", (first,)
        )
        assert jobs.recover_interrupted() == (0, 1)
        assert jobs.get(first).status == "failed"  # type: ignore[union-attr]
    finally:
        manager.close()


def test_cache_lru_enforces_hard_limit_and_never_touches_permanent_data(
    tmp_path: Path,
) -> None:
    manager = manager_for(tmp_path)
    permanent = manager.paths.library / "pdfs" / "kept.pdf"
    permanent.write_bytes(b"permanent-pdf")
    settings = SettingsRepository(manager.require_core())
    settings.set("preference", {"keep": True})
    clock = [1.0]
    cache = CacheManager(
        manager.require_cache(),
        manager.paths.cache,
        target_bytes=60,
        hard_limit_bytes=100,
        clock=lambda: clock[0],
    )
    try:
        cache.put("api", "old", b"a" * 50)
        clock[0] += 1
        cache.put("ocr", "middle", b"b" * 40)
        clock[0] += 1
        cache.put("api", "new", b"c" * 50)
        assert cache.get("old") is None
        assert cache.get("middle") is None
        assert cache.get("new") == b"c" * 50
        assert cache.stats().bytes <= 100
        assert permanent.read_bytes() == b"permanent-pdf"
        assert settings.get("preference") == {"keep": True}
        with pytest.raises(StorageError, match="single cache entry"):
            cache.put("api", "too-large", b"x" * 101)
    finally:
        manager.close()


def test_backup_restore_is_integrity_checked_and_excludes_pdf_files(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    pdf = manager.paths.library / "pdfs" / "original.pdf"
    pdf.write_bytes(b"not included in database backup")
    settings = SettingsRepository(manager.require_core())
    settings.set("value", "before")
    core = manager.require_core()
    paper_id = PaperRepository(core).create(PaperDraft("Persistent paper"))
    now = utc_now()
    core.execute(
        "INSERT INTO libraries(name, created_at, updated_at) VALUES('Project', ?, ?)",
        (now, now),
    )
    library_id = int(manager.require_core().last_insert_rowid())
    core.execute(
        "INSERT INTO library_papers(library_id, paper_id, added_at) VALUES(?, ?, ?)",
        (library_id, paper_id, now),
    )
    core.execute(
        """
        INSERT INTO paper_notes(paper_id, library_id, body, created_at, updated_at)
        VALUES(?, ?, 'note body', ?, ?)
        """,
        (paper_id, library_id, now, now),
    )
    note_id = int(core.last_insert_rowid())
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    file_id = FileRepository(core, manager.paths.library).register(
        sha256=digest,
        relative_path="pdfs/original.pdf",
        original_name="original.pdf",
        size_bytes=pdf.stat().st_size,
        page_count=1,
    )
    core.execute(
        "INSERT INTO paper_files(paper_id, file_id, created_at) VALUES(?, ?, ?)",
        (paper_id, file_id, now),
    )
    core.execute(
        """
        INSERT INTO pdf_annotations(
            file_id, paper_id, note_id, annotation_type, page_number, color,
            selected_text, rects_json, created_at, updated_at
        ) VALUES(?, ?, ?, 'highlight', 1, '#ffee66', 'text', '[]', ?, ?)
        """,
        (file_id, paper_id, note_id, now, now),
    )
    core.execute(
        """
        INSERT INTO translations(
            paper_id, field_name, source_hash, target_language, model_version,
            glossary_version, translated_text, created_at
        ) VALUES(?, 'title', 'source-hash', 'zh', 'test-model', 'v1', '译文', ?)
        """,
        (paper_id, now),
    )
    backup = create_core_backup(manager, manual=True)
    settings.set("value", "after")
    protective = restore_core_backup(manager, backup)
    try:
        assert SettingsRepository(manager.require_core()).get("value") == "before"
        assert manager.integrity()["core"] == "ok"
        for table in (
            "papers",
            "libraries",
            "library_papers",
            "paper_notes",
            "files",
            "paper_files",
            "pdf_annotations",
            "translations",
        ):
            count = require_row(
                manager.require_core().execute(f"SELECT count(*) FROM {table}").fetchone(),
                f"counting restored {table}",
            )[0]
            assert count == 1
        assert protective.is_file()
        assert pdf.is_file()
        assert b"not included in database backup" not in backup.read_bytes()
        assert backup.with_suffix(".json").read_text(encoding="utf-8").find(
            '"includes_pdf_files": false'
        ) >= 0
    finally:
        manager.close()


def test_automatic_backup_retention_keeps_ten_and_never_deletes_manual(
    tmp_path: Path,
) -> None:
    manager = manager_for(tmp_path)
    try:
        manual = create_core_backup(manager, manual=True)
        for _ in range(12):
            create_core_backup(manager, manual=False)
        assert len(list(manager.paths.backups.glob("core-auto-*.db"))) == 10
        assert manual.is_file()
    finally:
        manager.close()


def test_missing_pdf_can_only_be_relinked_by_matching_hash(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    try:
        content = b"%PDF-1.7 fixed sample"
        digest = hashlib.sha256(content).hexdigest()
        relative = f"pdfs/{digest[:2]}/{digest}.pdf"
        repository = FileRepository(manager.require_core(), manager.paths.library)
        file_id = repository.register(
            sha256=digest,
            relative_path=relative,
            original_name="sample.pdf",
            size_bytes=len(content),
            page_count=1,
        )
        missing = repository.scan_missing()
        assert [item.id for item in missing] == [file_id]
        wrong = tmp_path / "wrong.pdf"
        wrong.write_bytes(b"wrong")
        with pytest.raises(StorageError, match="does not match"):
            repository.relink(file_id, wrong)
        replacement = tmp_path / "replacement.pdf"
        replacement.write_bytes(content)
        restored = repository.relink(file_id, replacement)
        assert restored.read_bytes() == content
        assert repository.scan_missing() == []
    finally:
        manager.close()


def test_logs_redact_credentials_and_manifest_excludes_private_content(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "app")
    paths.ensure()
    logger = configure_logging(paths)
    logger.info("request api_key=visible-secret token=also-secret status=failed")
    for handler in logger.handlers:
        handler.flush()
    log_text = (paths.logs / "app.log").read_text(encoding="utf-8")
    assert "visible-secret" not in log_text
    assert "also-secret" not in log_text
    assert log_text.count("[REDACTED]") == 2
    manifest = diagnostic_manifest(paths)
    excluded = manifest["excluded"]
    assert isinstance(excluded, list)
    assert "PDF contents" in excluded
    assert "API keys" in excluded
    logging.shutdown()


def test_core_database_rejects_orphan_file_relationship(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    try:
        paper_id = PaperRepository(manager.require_core()).create(PaperDraft("Paper"))
        with pytest.raises(apsw.ConstraintError):
            manager.require_core().execute(
                """
                INSERT INTO paper_files(paper_id, file_id, created_at)
                VALUES(?, 999999, 'now')
                """,
                (paper_id,),
            )
    finally:
        manager.close()
