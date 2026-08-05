from __future__ import annotations

import hashlib
from pathlib import Path

from catalyst_literature.config import AppPaths
from catalyst_literature.library import LibraryService
from catalyst_literature.pdfs.reader import PdfReaderService
from catalyst_literature.storage.database import DatabaseManager, require_row, utc_now
from catalyst_literature.storage.files import FileRepository
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository

from .helpers import write_text_pdf


def setup_reader(
    tmp_path: Path,
) -> tuple[DatabaseManager, PdfReaderService, int, int, Path, str]:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    core = manager.require_core()
    paper_id = PaperRepository(core).create(PaperDraft("Reader paper"))
    path = manager.paths.library / "pdfs" / "reader.pdf"
    content = write_text_pdf(path, ["Reader catalyst content " + "word " * 20])
    digest = hashlib.sha256(content).hexdigest()
    file_id = FileRepository(core, manager.paths.library).register(
        sha256=digest,
        relative_path="pdfs/reader.pdf",
        original_name="reader.pdf",
        size_bytes=len(content),
        page_count=1,
    )
    core.execute(
        "INSERT INTO paper_files(paper_id, file_id, created_at) VALUES(?, ?, ?)",
        (paper_id, file_id, utc_now()),
    )
    service = PdfReaderService(core, LibraryService(core, manager.paths))
    return manager, service, paper_id, file_id, path, digest


def test_position_annotations_notes_filters_and_original_hash_are_durable(
    tmp_path: Path,
) -> None:
    manager, service, paper_id, file_id, path, original_hash = setup_reader(tmp_path)
    try:
        service.save_position(file_id, paper_id, 99, 1.4, 220)
        position = service.get_position(file_id, paper_id)
        assert position.page_number == 1
        assert position.scale == 1.4
        assert position.scroll_offset == 220
        created: list[int] = []
        for annotation_type in ("highlight", "underline", "comment"):
            created.append(
                service.create_annotation(
                    file_id,
                    paper_id,
                    annotation_type=annotation_type,
                    page_number=1,
                    color="#F4D35E",
                    selected_text=f"selected {annotation_type}",
                    prefix_text="before",
                    suffix_text="after",
                    rects=[{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}],
                    comment_text="kinetics insight" if annotation_type == "comment" else "",
                )
            )
        assert len(service.list_annotations(file_id, paper_id)) == 3
        assert len(
            service.list_annotations(file_id, paper_id, annotation_type="underline")
        ) == 1
        assert len(service.list_annotations(file_id, paper_id, query="kinetics")) == 1
        core = manager.require_core()
        note_count = require_row(
            core.execute("SELECT count(*) FROM paper_notes").fetchone(), "notes"
        )[0]
        assert note_count == 3
        service.update_annotation(created[2], color="#00AA88", comment_text="updated comment")
        updated = service.list_annotations(file_id, paper_id, query="updated")[0]
        assert updated["color"] == "#00AA88"
        service.delete_annotation(created[1])
        assert len(service.list_annotations(file_id, paper_id)) == 2
        note_count = require_row(
            core.execute("SELECT count(*) FROM paper_notes").fetchone(), "notes"
        )[0]
        assert note_count == 2
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
    finally:
        manager.close()
