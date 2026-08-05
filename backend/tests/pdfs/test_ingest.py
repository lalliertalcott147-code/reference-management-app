from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from catalyst_literature.config import AppPaths
from catalyst_literature.pdfs.ingest import PdfIngestService, PdfUploadError, new_upload_token
from catalyst_literature.storage.database import DatabaseManager, require_row
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository

from .helpers import write_text_pdf


def stage(
    service: PdfIngestService, source: Path, paper_id: int | None = None
):
    token = new_upload_token()
    data = source.read_bytes()
    service.temporary_path(token).write_bytes(data)
    return service.preview_staged(
        token=token,
        filename=source.name,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        paper_id=paper_id,
    )


def test_content_addressed_upload_exact_dedup_and_original_can_disappear(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    service = PdfIngestService(manager.require_core(), manager.paths)
    paper_id = PaperRepository(manager.require_core()).create(PaperDraft("Copper Catalyst"))
    source = tmp_path / "download.pdf"
    write_text_pdf(
        source, ["Copper Catalyst", "Author One", "Abstract " + "a" * 90, "Introduction"]
    )
    try:
        first = stage(service, source, paper_id)
        assert first.preview["duplicate_level"] == "none"
        linked_paper, file_id, permanent, deduplicated = service.confirm(
            token=first.token, paper_id=paper_id, resolution="attach"
        )
        assert linked_paper == paper_id
        assert deduplicated is False
        source.unlink()
        assert permanent.is_file()

        renamed = tmp_path / "renamed.pdf"
        renamed.write_bytes(permanent.read_bytes())
        duplicate = stage(service, renamed, paper_id)
        assert duplicate.preview["duplicate_level"] == "exact"
        _, duplicate_file, _, deduplicated = service.confirm(
            token=duplicate.token, paper_id=paper_id, resolution="link_existing"
        )
        assert duplicate_file == file_id
        assert deduplicated is True
        core = manager.require_core()
        assert require_row(core.execute("SELECT count(*) FROM files").fetchone(), "files")[0] == 1
        link_count = require_row(
            core.execute("SELECT count(*) FROM paper_files").fetchone(), "links"
        )[0]
        assert link_count == 1
    finally:
        manager.close()


def test_same_doi_requires_explicit_version_decision_and_invalid_pdf_is_removed(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    core = manager.require_core()
    paper_id = PaperRepository(core).create(
        PaperDraft("Versioned Catalyst", doi="10.1000/version", year=2026)
    )
    service = PdfIngestService(core, manager.paths)
    source = tmp_path / "publisher.pdf"
    write_text_pdf(
        source, ["Versioned Catalyst", "Author", "2026 DOI 10.1000/version", "Publisher"]
    )
    try:
        first = stage(service, source, paper_id)
        assert first.preview["duplicate_level"] == "none"
        service.confirm(token=first.token, paper_id=paper_id, resolution="attach")

        author_copy = tmp_path / "author-version.pdf"
        write_text_pdf(
            author_copy,
            ["Versioned Catalyst", "Author", "2026 DOI 10.1000/version", "Author manuscript"],
        )
        preview = stage(service, author_copy, paper_id)
        assert preview.preview["duplicate_level"] == "doi"
        with pytest.raises(PdfUploadError, match="明确选择"):
            service.confirm(token=preview.token, paper_id=paper_id, resolution="attach")
        _, _, permanent, _ = service.confirm(
            token=preview.token, paper_id=paper_id, resolution="keep_version"
        )
        assert permanent.is_file()

        bad_token = new_upload_token()
        bad = service.temporary_path(bad_token)
        bad.write_bytes(b"not a pdf")
        with pytest.raises(PdfUploadError, match="不是 PDF"):
            service.preview_staged(
                token=bad_token,
                filename="fake.pdf",
                sha256=hashlib.sha256(b"not a pdf").hexdigest(),
                size_bytes=9,
                paper_id=None,
            )
        assert not bad.exists()
    finally:
        manager.close()
