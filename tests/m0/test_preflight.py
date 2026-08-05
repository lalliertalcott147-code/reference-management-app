from __future__ import annotations

import subprocess
from pathlib import Path

import apsw

# pypdfium2 5.12.1 does not publish a PEP 561 marker or typing stubs.
import pypdfium2 as pdfium  # type: ignore[import-untyped]

from scripts.preflight import (
    MIN_SQLITE,
    check_sqlite,
    collect,
    configure_runtime_home,
    validate,
)

ROOT = Path(__file__).resolve().parents[2]


def test_apsw_meets_sqlite_floor() -> None:
    current = tuple(int(part) for part in apsw.sqlitelibversion().split(".")[:3])
    assert current >= MIN_SQLITE


def test_fts5_and_wal_are_enabled() -> None:
    _, fts5, wal = check_sqlite()
    assert fts5 is True
    assert wal is True


def test_pdfium_can_create_reopen_and_render(tmp_path: Path) -> None:
    pdf_path = tmp_path / "probe.pdf"
    document = pdfium.PdfDocument.new()
    document.new_page(width=200, height=300)
    document.save(pdf_path)
    document.close()

    reopened = pdfium.PdfDocument(pdf_path)
    assert len(reopened) == 1
    bitmap = reopened[0].render(scale=0.25)
    assert bitmap.width == 50
    assert bitmap.height == 75
    reopened.close()


def test_preflight_report_has_required_capacity() -> None:
    report = collect()
    assert report.logical_cpus is not None and report.logical_cpus >= 2
    assert report.memory_gib >= 8
    assert report.disk_free_gib >= 5
    assert validate(report) == []


def test_paddle_can_execute_tensor_operation() -> None:
    configure_runtime_home()
    import paddle

    result = paddle.matmul(paddle.ones([1, 2]), paddle.ones([2, 1])).numpy()
    assert result.tolist() == [[2.0]]


def test_packaged_probe_runs() -> None:
    executable = ROOT / "dist" / "catalyst-preflight-probe.exe"
    assert executable.exists(), "Run scripts/build-m0-probe.ps1 before pytest"
    result = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True, timeout=20
    )
    assert '"probe": "ok"' in result.stdout
