from __future__ import annotations

import os
import random
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import pytest
from catalyst_literature.config import AppPaths
from catalyst_literature.importers.models import ImportValidationError
from catalyst_literature.importers.validation import detect_format
from catalyst_literature.search.cache import SearchCache
from catalyst_literature.search.models import SearchQuery
from catalyst_literature.search.service import SearchService
from catalyst_literature.storage.cache import (
    DEFAULT_HARD_LIMIT_BYTES,
    DEFAULT_TARGET_BYTES,
    CacheManager,
)
from catalyst_literature.storage.database import (
    DatabaseManager,
    apply_migrations,
    open_database,
    transaction,
)
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository
from catalyst_literature.storage.schema import CORE_MIGRATIONS
from catalyst_literature.updates import PreferenceService, RecommendationService


class NeverCalledSource:
    name = "crossref"

    def __init__(self) -> None:
        self.called = False

    def search(self, _query: SearchQuery):
        self.called = True
        raise AssertionError("offline search attempted a network source")


def test_upgrade_from_previous_schema_preserves_data_and_creates_backup(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "app")
    paths.ensure()
    legacy = open_database(paths.data / "core.db")
    apply_migrations(legacy, CORE_MIGRATIONS[:5])
    paper_id = PaperRepository(legacy).create(PaperDraft("Legacy paper", year=2025))
    PreferenceService(legacy).save_topic("legacy", "catalysis")
    legacy.close()

    manager = DatabaseManager(paths)
    manager.initialize()
    try:
        assert manager.require_core().execute(
            "SELECT title_original FROM papers WHERE id=?", (paper_id,)
        ).fetchone()[0] == "Legacy paper"
        assert manager.require_core().execute(
            "SELECT name FROM research_topics"
        ).fetchone()[0] == "legacy"
        assert manager.require_core().execute(
            "SELECT max(version) FROM schema_migrations"
        ).fetchone()[0] == 6
        assert list(paths.backups.glob("pre-migration-v5-*.db"))
    finally:
        manager.close()


def test_interrupted_transaction_rolls_back_without_partial_rows(tmp_path: Path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    connection = manager.require_core()
    with (
        pytest.raises(RuntimeError, match="simulated power loss"),
        transaction(connection),
    ):
        PaperRepository(connection).create(PaperDraft("Never committed"))
        raise RuntimeError("simulated power loss")
    assert connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 0
    assert manager.integrity()["core"] == "ok"
    manager.close()


def _sparse_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.seek(size - 1)
        handle.write(b"\0")


def test_real_500_mb_cache_boundary_prunes_lru_and_preserves_pdf(tmp_path: Path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    permanent = manager.paths.library / "pdfs" / "permanent.pdf"
    permanent.write_bytes(b"permanent")
    connection = manager.require_cache()
    now = time.time()
    sizes = (245 * 1024 * 1024, 245 * 1024 * 1024)
    for index, size in enumerate(sizes):
        relative = f"stress/{index}.cache"
        _sparse_file(manager.paths.cache / relative, size)
        connection.execute(
            """
            INSERT INTO cache_entries(
                category, cache_key, relative_path, size_bytes,
                created_at, last_accessed_at
            ) VALUES('stress', ?, ?, ?, ?, ?)
            """,
            (f"old-{index}", relative, size, now, now + index),
        )
    cache = CacheManager(connection, manager.paths.cache)
    assert cache.stats().bytes == 490 * 1024 * 1024
    cache.put("stress", "new", b"x" * (20 * 1024 * 1024))
    assert cache.stats().bytes <= DEFAULT_TARGET_BYTES
    assert cache.stats().bytes <= DEFAULT_HARD_LIMIT_BYTES
    assert not (manager.paths.cache / "stress/0.cache").exists()
    assert permanent.read_bytes() == b"permanent"
    manager.close()


def test_import_detector_fuzz_has_only_controlled_rejections() -> None:
    generator = random.Random(20260805)
    for index in range(250):
        payload = generator.randbytes(generator.randint(0, 4096))
        with suppress(ImportValidationError):
            detect_format(f"fuzz-{index}.bin", payload)


def test_large_local_library_recommendations_remain_bounded(tmp_path: Path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    connection = manager.require_core()
    now = datetime.now(UTC).isoformat()
    with transaction(connection):
        for index in range(3_000):
            connection.execute(
                """
                INSERT INTO papers(
                    title_original, normalized_title, journal_title,
                    publication_year, created_at, updated_at
                ) VALUES(?, ?, 'Catalysis Today', 2026, ?, ?)
                """,
                (
                    f"Photocatalysis paper {index}",
                    f"photocatalysis paper {index}",
                    now,
                    now,
                ),
            )
    PreferenceService(connection).save_topic("光催化", "photocatalysis")
    started = time.monotonic()
    recommendations = RecommendationService(connection).recommend(limit=20)
    elapsed = time.monotonic() - started
    assert len(recommendations) == 20
    assert elapsed < 10
    manager.close()


def test_offline_mode_never_calls_external_source(tmp_path: Path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    source = NeverCalledSource()
    service = SearchService(
        (source,),  # type: ignore[arg-type]
        SearchCache(CacheManager(manager.require_cache(), manager.paths.cache)),
    )
    result = service.search(SearchQuery("catalysis"), online=False)
    assert source.called is False
    assert result.papers == ()
    assert result.statuses[0].state == "offline"
    manager.close()


def test_packaged_resource_path_cannot_be_overridden_by_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from catalyst_literature.runtime_resources import resource_root

    original = Path.cwd()
    os.chdir(tmp_path)
    try:
        assert resource_root() != tmp_path.resolve()
    finally:
        os.chdir(original)
