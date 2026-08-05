from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import apsw

from .database import DatabaseManager, StorageError, require_row, utc_now


def backup_database(source: apsw.Connection, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    destination = apsw.Connection(str(temporary))
    try:
        with destination.backup("main", source, "main") as backup:
            while not backup.done:
                backup.step(256)
        row = require_row(
            destination.execute("PRAGMA integrity_check").fetchone(), "validating backup"
        )
        result = str(row[0])
        if result != "ok":
            raise StorageError(f"Backup integrity check failed: {result}")
    finally:
        destination.close()
    os.replace(temporary, target)
    return target


def create_core_backup(manager: DatabaseManager, *, manual: bool) -> Path:
    category = "manual" if manual else "auto"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = manager.paths.backups / f"core-{category}-{stamp}.db"
    backup_database(manager.require_core(), target)
    manifest = target.with_suffix(".json")
    manifest.write_text(
        json.dumps(
            {
                "created_at": utc_now(),
                "database": target.name,
                "includes_pdf_files": False,
                "note": "PDF originals are intentionally excluded",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not manual:
        prune_automatic_backups(manager.paths.backups)
    return target


def prune_automatic_backups(directory: Path, *, keep: int = 10) -> None:
    backups = sorted(directory.glob("core-auto-*.db"), key=lambda path: path.stat().st_mtime)
    for expired in backups[:-keep]:
        expired.unlink(missing_ok=True)
        expired.with_suffix(".json").unlink(missing_ok=True)


def validate_backup(path: Path) -> None:
    if not path.is_file():
        raise StorageError(f"Backup does not exist: {path}")
    connection = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY)
    try:
        row = require_row(
            connection.execute("PRAGMA integrity_check").fetchone(), "validating backup"
        )
        result = str(row[0])
        if result != "ok":
            raise StorageError(f"Backup integrity check failed: {result}")
    finally:
        connection.close()


def restore_core_backup(manager: DatabaseManager, backup_path: Path) -> Path:
    validate_backup(backup_path)
    protective = create_core_backup(manager, manual=True)
    manager.close()
    temporary = manager.core_path.with_suffix(".restore.part")
    temporary.unlink(missing_ok=True)
    source = apsw.Connection(str(backup_path), flags=apsw.SQLITE_OPEN_READONLY)
    destination = apsw.Connection(str(temporary))
    try:
        with destination.backup("main", source, "main") as backup:
            while not backup.done:
                backup.step(256)
    finally:
        destination.close()
        source.close()
    os.replace(temporary, manager.core_path)
    manager.initialize()
    return protective
