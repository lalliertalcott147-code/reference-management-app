from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import apsw

from ..config import AppPaths
from .schema import CACHE_MIGRATIONS, CORE_MIGRATIONS, Migration

MIN_SQLITE_VERSION = (3, 51, 3)


class StorageError(RuntimeError):
    """A local storage precondition or consistency check failed."""


def require_row(row: Any | None, context: str) -> tuple[Any, ...]:
    if row is None:
        raise StorageError(f"Expected a database row while {context}")
    return cast(tuple[Any, ...], row)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_storage_ready(paths: AppPaths, *, minimum_free_bytes: int = 100 * 1024 * 1024) -> None:
    paths.ensure()
    try:
        with tempfile.NamedTemporaryFile(
            dir=paths.root, prefix="write-check-", delete=True
        ) as file:
            file.write(b"ok")
            file.flush()
    except OSError as error:
        raise StorageError(f"Local data directory is not writable: {paths.root}") from error
    free_bytes = shutil.disk_usage(paths.root).free
    if free_bytes < minimum_free_bytes:
        raise StorageError(
            f"Insufficient disk space: {free_bytes} bytes free; {minimum_free_bytes} required"
        )


def open_database(path: Path, *, cache: bool = False) -> apsw.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = apsw.Connection(str(path))
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    if cache and path.stat().st_size == 0:
        connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
    journal_row = require_row(
        connection.execute("PRAGMA journal_mode=WAL").fetchone(), "enabling WAL"
    )
    journal_mode = str(journal_row[0]).lower()
    if journal_mode != "wal":
        connection.close()
        raise StorageError(f"Could not enable WAL for {path}")
    connection.execute("PRAGMA synchronous=NORMAL")
    version = tuple(int(part) for part in apsw.sqlitelibversion().split(".")[:3])
    if version < MIN_SQLITE_VERSION:
        connection.close()
        raise StorageError(
            f"SQLite {apsw.sqlitelibversion()} is below required 3.51.3"
        )
    return connection


@contextmanager
def transaction(connection: apsw.Connection, *, immediate: bool = True) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")


def current_schema_version(connection: apsw.Connection) -> int:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    row = require_row(
        connection.execute("SELECT max(version) FROM schema_migrations").fetchone(),
        "reading schema version",
    )
    return int(row[0] or 0)


def apply_migrations(
    connection: apsw.Connection,
    migrations: Sequence[Migration],
) -> int:
    current = current_schema_version(connection)
    versions = [migration.version for migration in migrations]
    if versions != sorted(set(versions)):
        raise StorageError("Migration versions must be unique and ordered")
    for migration in migrations:
        if migration.version <= current:
            continue
        if migration.version != current + 1:
            raise StorageError(
                f"Migration gap: database is at {current}, next migration is {migration.version}"
            )
        with transaction(connection):
            connection.execute(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES(?, ?, ?)",
                (migration.version, migration.name, utc_now()),
            )
        current = migration.version
    return current


class DatabaseManager:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.core_path = paths.data / "core.db"
        self.cache_path = paths.data / "cache.db"
        self.core: apsw.Connection | None = None
        self.cache: apsw.Connection | None = None

    def initialize(self) -> None:
        ensure_storage_ready(self.paths)
        core_existed = self.core_path.exists() and self.core_path.stat().st_size > 0
        core = open_database(self.core_path)
        cache = open_database(self.cache_path, cache=True)
        try:
            current = current_schema_version(core)
            latest = CORE_MIGRATIONS[-1].version
            if core_existed and current < latest:
                from .backup import backup_database

                backup_name = f"pre-migration-v{current}-{datetime.now():%Y%m%d%H%M%S}.db"
                backup_database(core, self.paths.backups / backup_name)
            apply_migrations(core, CORE_MIGRATIONS)
            apply_migrations(cache, CACHE_MIGRATIONS)
        except BaseException:
            core.close()
            cache.close()
            raise
        self.core = core
        self.cache = cache

    def checkpoint(self) -> None:
        for connection in (self.core, self.cache):
            if connection is not None:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        self.checkpoint()
        for connection in (self.cache, self.core):
            if connection is not None:
                connection.close()
        self.core = None
        self.cache = None

    def require_core(self) -> apsw.Connection:
        if self.core is None:
            raise StorageError("Core database is not initialized")
        return self.core

    def require_cache(self) -> apsw.Connection:
        if self.cache is None:
            raise StorageError("Cache database is not initialized")
        return self.cache

    def integrity(self) -> dict[str, str]:
        return {
            "core": str(
                require_row(
                    self.require_core().execute("PRAGMA integrity_check").fetchone(),
                    "checking core database",
                )[0]
            ),
            "cache": str(
                require_row(
                    self.require_cache().execute("PRAGMA integrity_check").fetchone(),
                    "checking cache database",
                )[0]
            ),
        }

    def __enter__(self) -> DatabaseManager:
        self.initialize()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
