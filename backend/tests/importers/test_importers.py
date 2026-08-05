from __future__ import annotations

import io
from pathlib import Path

import pytest
from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.importers.models import ImportValidationError
from catalyst_literature.importers.parsers import parse_wos_export
from catalyst_literature.importers.service import WosImportService
from catalyst_literature.importers.validation import detect_format
from catalyst_literature.security import SESSION_COOKIE, SessionManager
from catalyst_literature.storage.database import DatabaseManager, require_row
from fastapi.testclient import TestClient
from openpyxl import Workbook

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "wos"


def workbook_bytes(*, formula: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(
        [
            "Article Title",
            "Authors",
            "Source Title",
            "Publication Year",
            "DOI",
            "Accession Number",
            "Abstract",
        ]
    )
    sheet.append(
        [
            "Solar-driven CO2 conversion on copper catalysts",
            "Li, Ming; Smith, Anna",
            "Journal of Catalysis",
            "=2025+1" if formula else 2026,
            "10.1000/catalyst.2026",
            "WOS:000000000000001",
            "Copper catalysts convert carbon dioxide.",
        ]
    )
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


@pytest.mark.parametrize(
    ("name", "expected"),
    [("sample.txt", "wos_plain_text"), ("sample.ris", "ris")],
)
def test_content_signature_detection_and_parsing(name: str, expected: str) -> None:
    data = (FIXTURES / name).read_bytes()
    assert detect_format("misleading.bin", data) == expected
    parsed = parse_wos_export(name, data)
    assert parsed.format == expected
    assert len(parsed.records) == 2
    assert parsed.records[0].authors == ("Li, Ming", "Smith, Anna")
    assert parsed.records[0].abstract == (
        "Copper catalysts convert carbon dioxide under simulated sunlight."
    )
    assert parsed.records[1].doi is None


def test_excel_common_columns_are_mapped_without_executing_formulas() -> None:
    data = workbook_bytes()
    assert detect_format("export.xlsx", data) == "xlsx"
    parsed = parse_wos_export("export.xlsx", data)
    assert parsed.records[0].wos_uid == "WOS:000000000000001"
    assert parsed.records[0].year == 2026
    with pytest.raises(ImportValidationError, match="Formula cells"):
        parse_wos_export("formula.xlsx", workbook_bytes(formula=True))


@pytest.mark.parametrize(
    "data",
    [b"", b"%PDF-1.7 not an export", b"PK\x03\x04not-a-real-workbook", b"\xd0\xcf\x11\xe0old-xls"],
)
def test_unsupported_or_damaged_files_are_rejected(data: bytes) -> None:
    with pytest.raises(ImportValidationError):
        detect_format("export.xlsx", data)


def test_preview_writes_nothing_then_confirm_is_idempotent(tmp_path: Path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    service = WosImportService(manager.require_core())
    data = (FIXTURES / "sample.txt").read_bytes()
    try:
        preview = service.preview("sample.txt", data)
        assert preview.total == 2
        assert preview.new == 2
        assert preview.missing_doi == 1
        assert (
            require_row(
                manager.require_core().execute("SELECT count(*) FROM papers").fetchone(), "count"
            )[0]
            == 0
        )
        first = service.confirm(preview)
        assert (first.added, first.updated, first.skipped, first.failed) == (2, 0, 0, 0)
        second_preview = service.preview("sample.txt", data)
        assert (second_preview.new, second_preview.duplicates) == (0, 2)
        second = service.confirm(second_preview)
        assert (second.added, second.updated, second.skipped) == (0, 0, 2)
        assert (
            require_row(
                manager.require_core().execute("SELECT count(*) FROM papers").fetchone(), "count"
            )[0]
            == 2
        )
        assert (
            require_row(
                manager.require_core()
                .execute("SELECT count(*) FROM paper_sources WHERE source='wos_export'")
                .fetchone(),
                "source count",
            )[0]
            == 2
        )
    finally:
        manager.close()


def test_preview_reports_title_conflict_and_import_prefers_official_export(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "app"))
    manager.initialize()
    core = manager.require_core()
    now = "2026-01-01T00:00:00+00:00"
    core.execute(
        """
        INSERT INTO papers(
            doi, title_original, normalized_title, publication_year, created_at, updated_at
        ) VALUES('10.1000/catalyst.2026', 'Older title', 'older title', 2026, ?, ?)
        """,
        (now, now),
    )
    service = WosImportService(core)
    try:
        preview = service.preview("sample.ris", (FIXTURES / "sample.ris").read_bytes())
        assert preview.duplicates == 1
        assert preview.conflicts >= 1
        report = service.confirm(preview)
        assert report.updated == 1
        title = require_row(
            core.execute(
                "SELECT title_original FROM papers WHERE doi='10.1000/catalyst.2026'"
            ).fetchone(),
            "updated title",
        )[0]
        assert title == "Solar-driven CO2 conversion on copper catalysts"
    finally:
        manager.close()


def test_authenticated_preview_and_confirm_upload_endpoints(tmp_path: Path) -> None:
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "app"))
    manager = DatabaseManager(settings.paths)
    manager.initialize()
    sessions = SessionManager()
    app = create_app(
        settings,
        origin="http://127.0.0.1:43210",
        sessions=sessions,
        database=manager,
    )
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, sessions.session_token)
    headers = {"Origin": "http://127.0.0.1:43210"}
    data = (FIXTURES / "sample.txt").read_bytes()
    try:
        preview = client.post(
            "/api/import/wos/preview",
            files={"file": ("sample.txt", data, "text/plain")},
            headers=headers,
        )
        assert preview.status_code == 200
        assert preview.json()["new"] == 2
        report = client.post(
            "/api/import/wos/confirm",
            files={"file": ("sample.txt", data, "text/plain")},
            headers=headers,
        )
        assert report.status_code == 200
        assert report.json()["added"] == 2
    finally:
        manager.close()
