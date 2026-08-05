from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import apsw

from .database import StorageError, require_row, transaction

DEFAULT_TARGET_BYTES = 450 * 1024 * 1024
DEFAULT_HARD_LIMIT_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True)
class CacheStats:
    bytes: int
    entries: int
    by_category: dict[str, int]


class CacheManager:
    def __init__(
        self,
        connection: apsw.Connection,
        root: Path,
        *,
        target_bytes: int = DEFAULT_TARGET_BYTES,
        hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not 0 <= target_bytes <= hard_limit_bytes:
            raise ValueError("Cache target must be between zero and the hard limit")
        self.connection = connection
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.target_bytes = target_bytes
        self.hard_limit_bytes = hard_limit_bytes
        self.clock = clock

    def _path_for(self, category: str, key: str) -> Path:
        digest = hashlib.sha256(f"{category}:{key}".encode()).hexdigest()
        return self.root / category / digest[:2] / f"{digest}.cache"

    def _delete_row_and_file(self, row_id: int, relative_path: str) -> None:
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("Cache index contains an unsafe path")
        path.unlink(missing_ok=True)
        self.connection.execute("DELETE FROM cache_entries WHERE id=?", (row_id,))

    def _make_room(self, required_bytes: int, *, replacing_key: str | None = None) -> None:
        if required_bytes > self.hard_limit_bytes:
            raise StorageError("A single cache entry exceeds the hard cache limit")
        row = require_row(
            self.connection.execute(
                "SELECT coalesce(sum(size_bytes), 0) FROM cache_entries "
                "WHERE cache_key IS NOT ?",
                (replacing_key,),
            ).fetchone(),
            "calculating cache size",
        )
        used = int(row[0])
        if used + required_bytes <= self.hard_limit_bytes:
            return
        rows = self.connection.execute(
            """
            SELECT id, relative_path, size_bytes FROM cache_entries
            WHERE cache_key IS NOT ? ORDER BY last_accessed_at, id
            """,
            (replacing_key,),
        ).fetchall()
        for row_id, relative_path, size_bytes in rows:
            self._delete_row_and_file(int(str(row_id)), str(relative_path))
            used -= int(str(size_bytes))
            if used + required_bytes <= self.target_bytes:
                break
        if used + required_bytes > self.hard_limit_bytes:
            raise StorageError("Could not free enough cache space")

    def put(
        self,
        category: str,
        key: str,
        payload: bytes,
        *,
        expires_at: float | None = None,
    ) -> Path:
        now = float(self.clock())
        target = self._path_for(category, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".part")
        self._make_room(len(payload), replacing_key=key)
        temporary.write_bytes(payload)
        try:
            os.replace(temporary, target)
            relative = target.relative_to(self.root).as_posix()
            with transaction(self.connection):
                old = self.connection.execute(
                    "SELECT relative_path FROM cache_entries WHERE cache_key=?", (key,)
                ).fetchone()
                self.connection.execute(
                    """
                    INSERT INTO cache_entries(
                        category, cache_key, relative_path, size_bytes,
                        created_at, expires_at, last_accessed_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        category=excluded.category,
                        relative_path=excluded.relative_path,
                        size_bytes=excluded.size_bytes,
                        created_at=excluded.created_at,
                        expires_at=excluded.expires_at,
                        last_accessed_at=excluded.last_accessed_at
                    """,
                    (category, key, relative, len(payload), now, expires_at, now),
                )
                if old is not None and str(old[0]) != relative:
                    (self.root / str(old[0])).unlink(missing_ok=True)
        except BaseException:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return target

    def get(self, key: str) -> bytes | None:
        row = self.connection.execute(
            "SELECT id, relative_path, expires_at FROM cache_entries WHERE cache_key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        row_id, relative_path, expires_at = row
        now = float(self.clock())
        if expires_at is not None and float(expires_at) <= now:
            self._delete_row_and_file(int(str(row_id)), str(relative_path))
            return None
        path = (self.root / str(relative_path)).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            self.connection.execute("DELETE FROM cache_entries WHERE id=?", (row_id,))
            return None
        self.connection.execute(
            "UPDATE cache_entries SET last_accessed_at=? WHERE id=?", (now, row_id)
        )
        return path.read_bytes()

    def clear(self, *, category: str | None = None) -> int:
        if category is None:
            rows = self.connection.execute(
                "SELECT id, relative_path FROM cache_entries"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT id, relative_path FROM cache_entries WHERE category=?", (category,)
            ).fetchall()
        for row_id, relative_path in rows:
            self._delete_row_and_file(int(str(row_id)), str(relative_path))
        self.connection.execute("PRAGMA incremental_vacuum(64)")
        return len(rows)

    def stats(self) -> CacheStats:
        summary = require_row(
            self.connection.execute(
                "SELECT count(*), coalesce(sum(size_bytes), 0) FROM cache_entries"
            ).fetchone(),
            "summarizing cache",
        )
        by_category = {
            str(category): int(size)
            for category, size in self.connection.execute(
                "SELECT category, sum(size_bytes) FROM cache_entries GROUP BY category"
            )
        }
        return CacheStats(int(summary[1]), int(summary[0]), by_category)
