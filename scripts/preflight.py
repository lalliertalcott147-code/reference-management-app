from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MIN_SQLITE = (3, 51, 3)


def configure_runtime_home() -> Path:
    """Keep third-party model caches inside the app-controlled data boundary."""
    configured = os.environ.get("CATALYST_RUNTIME_HOME")
    runtime_home = (
        Path(configured)
        if configured
        else Path(tempfile.gettempdir()) / "CatalystLiteratureTestRuntime"
    )
    runtime_home.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(runtime_home.resolve())
    return runtime_home


@dataclass(frozen=True)
class PreflightReport:
    windows: str
    python: str
    logical_cpus: int | None
    memory_gib: float
    disk_free_gib: float
    sqlite: str
    fts5: bool
    wal: bool
    pypdfium2: str
    paddle: str
    paddleocr: str
    llama_cpp: str | None


class MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def total_memory_gib() -> float:
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return round(status.ullTotalPhys / 2**30, 2)


def module_version(module_name: str) -> str:
    module = importlib.import_module(module_name)
    for attribute in ("__version__", "VERSION", "version"):
        value = getattr(module, attribute, None)
        if value:
            return str(value)
    return "installed"


def check_sqlite() -> tuple[str, bool, bool]:
    import apsw

    version = apsw.sqlitelibversion()
    parsed = tuple(int(part) for part in version.split(".")[:3])
    if parsed < MIN_SQLITE:
        raise RuntimeError(f"SQLite {version} is below required 3.51.3")

    connection = apsw.Connection(":memory:")
    connection.execute("CREATE VIRTUAL TABLE probe_fts USING fts5(body)")
    connection.execute("INSERT INTO probe_fts(body) VALUES('catalysis literature')")
    match = connection.execute(
        "SELECT count(*) FROM probe_fts WHERE probe_fts MATCH 'catalysis'"
    ).get
    fts5 = match == 1

    temp_dir = Path.cwd() / "tests" / "artifacts"
    temp_dir.mkdir(parents=True, exist_ok=True)
    db_path = temp_dir / "preflight-wal.db"
    if db_path.exists():
        db_path.unlink()
    disk_connection = apsw.Connection(str(db_path))
    wal_mode = disk_connection.execute("PRAGMA journal_mode=WAL").get
    disk_connection.close()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()
    return version, fts5, str(wal_mode).lower() == "wal"


def find_llama() -> Path | None:
    candidates = [
        Path.cwd() / "vendor" / "llama.cpp" / "llama-server.exe",
        Path.cwd() / "vendor" / "llama.cpp" / "llama-cli.exe",
    ]
    return next((path for path in candidates if path.exists()), None)


def llama_version(executable: Path | None) -> str | None:
    if executable is None:
        return None
    result = subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or result.stderr).strip().splitlines()[0]


def collect() -> PreflightReport:
    configure_runtime_home()
    sqlite, fts5, wal = check_sqlite()
    disk = shutil.disk_usage(Path.cwd())
    return PreflightReport(
        windows=platform.platform(),
        python=platform.python_version(),
        logical_cpus=os.cpu_count(),
        memory_gib=total_memory_gib(),
        disk_free_gib=round(disk.free / 2**30, 2),
        sqlite=sqlite,
        fts5=fts5,
        wal=wal,
        pypdfium2=module_version("pypdfium2"),
        paddle=module_version("paddle"),
        paddleocr=module_version("paddleocr"),
        llama_cpp=llama_version(find_llama()),
    )


def validate(report: PreflightReport) -> list[str]:
    errors: list[str] = []
    if platform.system() != "Windows":
        errors.append("V1 requires Windows")
    if not report.fts5:
        errors.append("SQLite FTS5 probe failed")
    if not report.wal:
        errors.append("SQLite WAL probe failed")
    if report.memory_gib < 8:
        errors.append("At least 8 GiB RAM is required")
    if report.disk_free_gib < 5:
        errors.append("At least 5 GiB free disk is required for development")
    if report.llama_cpp is None:
        errors.append("llama.cpp portable binary is missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Catalyst Literature M0 preflight")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()
    report = collect()
    errors = validate(report)
    payload: dict[str, Any] = {"report": asdict(report), "errors": errors}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in asdict(report).items():
            print(f"{key}: {value}")
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
