from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from catalyst_literature.config import AppPaths
from catalyst_literature.library import LibraryService
from catalyst_literature.storage.database import DatabaseManager, require_row, utc_now
from catalyst_literature.storage.files import FileRepository
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository


def setup_library(tmp_path: Path) -> tuple[DatabaseManager, LibraryService, int, int]:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    service = LibraryService(manager.require_core(), manager.paths)
    paper_id = PaperRepository(manager.require_core()).create(
        PaperDraft("中文 Catalyst {Study}", doi="10.1000/library", journal="催化学报", year=2026)
    )
    library_id = service.create_library("项目 A")
    service.add_paper(library_id, paper_id)
    return manager, service, paper_id, library_id


def test_multiple_libraries_many_to_many_rename_reorder_and_restore(tmp_path: Path) -> None:
    manager, service, paper_id, first = setup_library(tmp_path)
    try:
        second = service.create_library("项目 B")
        service.add_paper(second, paper_id)
        service.add_paper(second, paper_id)
        service.rename_library(second, "项目 B 更新")
        service.reorder([second, first])
        listed = service.list_libraries()
        assert [(item.name, item.paper_count) for item in listed] == [
            ("项目 B 更新", 1),
            ("项目 A", 1),
        ]
        service.move_to_trash(first)
        assert [item.id for item in service.list_libraries()] == [second]
        service.restore_library(first)
        assert {item.id for item in service.list_libraries()} == {first, second}
    finally:
        manager.close()


def test_expired_library_purge_does_not_delete_shared_paper_or_pdf(tmp_path: Path) -> None:
    manager, service, paper_id, library_id = setup_library(tmp_path)
    content = b"permanent pdf"
    digest = hashlib.sha256(content).hexdigest()
    pdf = manager.paths.library / "pdfs" / digest[:2] / f"{digest}.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(content)
    file_id = FileRepository(manager.require_core(), manager.paths.library).register(
        sha256=digest,
        relative_path=pdf.relative_to(manager.paths.library).as_posix(),
        original_name="paper.pdf",
        size_bytes=len(content),
        page_count=1,
    )
    manager.require_core().execute(
        "INSERT INTO paper_files(paper_id, file_id, created_at) VALUES(?, ?, ?)",
        (paper_id, file_id, utc_now()),
    )
    old = datetime.now(UTC) - timedelta(days=31)
    manager.require_core().execute(
        "UPDATE libraries SET deleted_at=? WHERE id=?", (old.isoformat(), library_id)
    )
    try:
        assert service.purge_expired() == 1
        assert (
            require_row(
                manager.require_core().execute("SELECT count(*) FROM papers").fetchone(),
                "paper count",
            )[0]
            == 1
        )
        assert (
            require_row(
                manager.require_core().execute("SELECT count(*) FROM files").fetchone(),
                "file count",
            )[0]
            == 1
        )
        assert pdf.read_bytes() == content
    finally:
        manager.close()


def test_tags_merge_batch_assignment_and_full_text_search(tmp_path: Path) -> None:
    manager, service, paper_id, library_id = setup_library(tmp_path)
    try:
        source = service.create_tag("光催化")
        target = service.create_tag("Photocatalysis")
        service.tag_papers(source, [paper_id], library_id)
        service.tag_papers(source, [paper_id], library_id)
        service.merge_tags(source, target)
        assert (
            require_row(
                manager.require_core().execute("SELECT count(*) FROM paper_tags").fetchone(),
                "tag count",
            )[0]
            == 1
        )
        results = service.list_papers(query="Photocatalysis")
        assert [item["id"] for item in results] == [paper_id]
    finally:
        manager.close()


def test_note_autosave_versions_and_fts_are_transactional(tmp_path: Path) -> None:
    manager, service, paper_id, library_id = setup_library(tmp_path)
    try:
        note_id, version = service.save_note(paper_id, "first catalyst note", library_id=library_id)
        assert version == 1
        same_id, version = service.save_note(paper_id, "updated copper insight", note_id=note_id)
        assert same_id == note_id
        assert version == 2
        versions = (
            manager.require_core()
            .execute(
                "SELECT version, body FROM paper_note_versions WHERE note_id=? ORDER BY version",
                (note_id,),
            )
            .fetchall()
        )
        assert versions == [(1, "first catalyst note"), (2, "updated copper insight")]
        assert service.list_papers(query="copper")[0]["id"] == paper_id
    finally:
        manager.close()


def test_global_note_workspace_cards_collect_article_context_and_persist_layout(
    tmp_path: Path,
) -> None:
    manager, service, paper_id, library_id = setup_library(tmp_path)
    core = manager.require_core()
    try:
        core.execute(
            """
            INSERT INTO abstracts(
                paper_id, language, content, content_hash, is_preferred, created_at
            ) VALUES(?, 'en', 'Original abstract', 'workspace-abstract', 1, ?)
            """,
            (paper_id, utc_now()),
        )
        core.execute(
            "UPDATE papers SET title_zh='中文题目' WHERE id=?", (paper_id,)
        )
        core.execute(
            """
            INSERT INTO translations(
                paper_id, field_name, source_hash, target_language, model_version,
                glossary_version, translated_text, created_at
            ) VALUES(?, 'abstract', 'workspace-source', 'zh', 'test', 'none',
                     '中文摘要', ?)
            """,
            (paper_id, utc_now()),
        )
        note_id, _version = service.save_note(
            paper_id, "first article note", library_id=library_id
        )
        same_note, version = service.append_note(
            paper_id, "translated excerpt", library_id=library_id
        )
        assert (same_note, version) == (note_id, 2)

        initial = service.get_workspace(library_id)
        assert initial["body"] == ""
        assert initial["cards"] == []
        assert service.save_workspace(
            library_id,
            body="overall synthesis",
            note_x=80,
            note_y=90,
            note_width=600,
            note_height=320,
        ) == 2
        card_id = service.add_workspace_card(library_id, paper_id)
        service.update_workspace_card(card_id, x=710, y=120, width=360, height=420)

        workspace = service.get_workspace(library_id)
        assert workspace["body"] == "overall synthesis"
        assert (workspace["note_x"], workspace["note_y"]) == (80.0, 90.0)
        cards = workspace["cards"]
        assert isinstance(cards, list)
        card = cards[0]
        assert card["title_translation"] == "中文题目"
        assert card["abstract"] == "Original abstract"
        assert card["abstract_translation"] == "中文摘要"
        assert card["x"] == 710.0
        assert card["notes"][0]["body"] == "first article note\n\ntranslated excerpt"
    finally:
        manager.close()


def test_like_saved_and_reading_status_are_independent(tmp_path: Path) -> None:
    manager, service, paper_id, _library_id = setup_library(tmp_path)
    try:
        service.set_state(
            paper_id,
            liked=True,
            disliked=False,
            saved=False,
            reading_status="read",
        )
        row = require_row(
            manager.require_core()
            .execute(
                """
                SELECT liked, disliked, saved, reading_status
                FROM user_paper_state WHERE paper_id=?
                """,
                (paper_id,),
            )
            .fetchone(),
            "paper state",
        )
        assert row == (1, 0, 0, "read")
    finally:
        manager.close()


def test_bibtex_ris_and_csv_exports_preserve_unicode_and_special_characters(
    tmp_path: Path,
) -> None:
    manager, service, paper_id, _library_id = setup_library(tmp_path)
    try:
        for format_name, expected_name in (
            ("bibtex", "papers.bib"),
            ("ris", "papers.ris"),
            ("csv", "papers.csv"),
        ):
            filename, content = service.export([paper_id], format_name)
            assert filename == expected_name
            decoded = content.decode("utf-8-sig")
            assert "中文 Catalyst" in decoded
            assert "10.1000/library" in decoded
        assert r"\{Study\}" in service.export([paper_id], "bibtex")[1].decode()
    finally:
        manager.close()


def test_storage_usage_separates_pdf_cache_models_backups_and_logs(tmp_path: Path) -> None:
    manager, service, _paper_id, _library_id = setup_library(tmp_path)
    try:
        (manager.paths.library / "pdfs" / "sample.pdf").write_bytes(b"p" * 11)
        (manager.paths.models / "model.gguf").write_bytes(b"m" * 13)
        (manager.paths.cache / "entry.cache").write_bytes(b"c" * 17)
        (manager.paths.backups / "backup.db").write_bytes(b"b" * 19)
        (manager.paths.logs / "app.log").write_bytes(b"l" * 23)
        usage = service.storage_usage()
        assert usage["pdf"] == 11
        assert usage["models"] == 13
        assert usage["cache"] >= 17
        assert usage["backups"] == 19
        assert usage["logs"] == 23
        assert usage["database"] > 0
    finally:
        manager.close()
