from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import apsw
import pytest
from catalyst_literature.config import AppPaths
from catalyst_literature.storage.database import (
    DatabaseManager,
    StorageError,
    apply_migrations,
    current_schema_version,
    ensure_storage_ready,
    open_database,
    require_row,
    transaction,
)
from catalyst_literature.storage.repositories import (
    PaperDraft,
    PaperRepository,
    SettingsRepository,
)
from catalyst_literature.storage.schema import CORE_MIGRATIONS, Migration


def initialized_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    return manager


def scalar(connection: apsw.Connection, sql: str) -> object:
    return require_row(connection.execute(sql).fetchone(), sql)[0]


def test_fresh_database_has_required_pragmas_schema_and_fts(tmp_path: Path) -> None:
    manager = initialized_manager(tmp_path)
    try:
        core = manager.require_core()
        cache = manager.require_cache()
        assert scalar(core, "PRAGMA journal_mode") == "wal"
        assert scalar(core, "PRAGMA foreign_keys") == 1
        assert scalar(cache, "PRAGMA journal_mode") == "wal"
        assert scalar(cache, "PRAGMA auto_vacuum") == 2
        assert current_schema_version(core) == CORE_MIGRATIONS[-1].version
        tables = {
            str(row[0])
            for row in core.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "papers",
            "translations",
            "files",
            "pdf_annotations",
            "jobs",
            "library_workspaces",
            "library_workspace_cards",
        } <= tables
        core.execute(
            "INSERT INTO paper_fts(paper_id, title_original) VALUES(1, 'photocatalysis')"
        )
        assert (
            scalar(
                core,
                "SELECT paper_id FROM paper_fts WHERE paper_fts MATCH 'photocatalysis'",
            )
            == 1
        )
        assert manager.integrity() == {"core": "ok", "cache": "ok"}
    finally:
        manager.close()


def test_constraints_and_transaction_rollback_are_enforced(tmp_path: Path) -> None:
    manager = initialized_manager(tmp_path)
    try:
        papers = PaperRepository(manager.require_core())
        papers.create(PaperDraft("First", doi="https://doi.org/10.1000/Test"))
        with pytest.raises(apsw.ConstraintError):
            papers.create(PaperDraft("Duplicate", doi="10.1000/test"))

        with pytest.raises(RuntimeError), transaction(manager.require_core()):
            manager.require_core().execute(
                "INSERT INTO libraries(name, created_at, updated_at) VALUES('Transient','x','x')"
            )
            raise RuntimeError("interrupt the multi-table operation")
        assert (
            scalar(
                manager.require_core(),
                "SELECT count(*) FROM libraries WHERE name='Transient'",
            )
            == 0
        )
    finally:
        manager.close()


def test_forward_upgrade_creates_pre_migration_backup(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "app")
    paths.ensure()
    old = open_database(paths.data / "core.db")
    apply_migrations(old, CORE_MIGRATIONS[:1])
    SettingsRepository(old).set("from_v1", True)
    old.close()

    manager = DatabaseManager(paths)
    manager.initialize()
    try:
        assert current_schema_version(manager.require_core()) == CORE_MIGRATIONS[-1].version
        assert SettingsRepository(manager.require_core()).get("from_v1") is True
        backups = list(paths.backups.glob("pre-migration-v1-*.db"))
        assert len(backups) == 1
        backup = apsw.Connection(str(backups[0]), flags=apsw.SQLITE_OPEN_READONLY)
        try:
            assert current_schema_version(backup) == 1
        finally:
            backup.close()
    finally:
        manager.close()


def test_failed_migration_rolls_back_without_advancing_version(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "broken.db")
    bad = Migration(
        1,
        "bad",
        "CREATE TABLE must_rollback(id INTEGER); INSERT INTO table_that_does_not_exist VALUES(1);",
    )
    try:
        with pytest.raises(apsw.SQLError):
            apply_migrations(connection, (bad,))
        assert current_schema_version(connection) == 0
        assert (
            scalar(
                connection,
                "SELECT count(*) FROM sqlite_master WHERE name='must_rollback'",
            )
            == 0
        )
    finally:
        connection.close()


def test_concurrent_connections_respect_busy_wait_and_keep_all_writes(tmp_path: Path) -> None:
    manager = initialized_manager(tmp_path)
    database_path = manager.core_path
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        connection = open_database(database_path)
        try:
            SettingsRepository(connection).set(f"thread-{index}", index)
        except BaseException as error:
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    try:
        assert errors == []
        assert (
            scalar(
                manager.require_core(),
                "SELECT count(*) FROM app_settings WHERE key LIKE 'thread-%'",
            )
            == 8
        )
    finally:
        manager.close()


def test_committed_write_survives_abrupt_process_exit(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "app")
    manager = DatabaseManager(paths)
    manager.initialize()
    manager.close()
    code = (
        "import os,sys; from pathlib import Path; "
        "from catalyst_literature.storage.database import open_database; "
        "from catalyst_literature.storage.repositories import SettingsRepository; "
        "c=open_database(Path(sys.argv[1])); SettingsRepository(c).set('abrupt', {'kept': True}); "
        "os._exit(0)"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    completed = subprocess.run(
        [sys.executable, "-c", code, str(paths.data / "core.db")],
        env=environment,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0
    reopened = DatabaseManager(paths)
    reopened.initialize()
    try:
        assert SettingsRepository(reopened.require_core()).get("abrupt") == {"kept": True}
    finally:
        reopened.close()


def test_low_disk_space_blocks_storage_initialization(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "app")
    with pytest.raises(StorageError, match="Insufficient disk space"):
        ensure_storage_ready(paths, minimum_free_bytes=10**18)
