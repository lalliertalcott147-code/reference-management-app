from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from catalyst_literature.config import AppPaths
from catalyst_literature.diagnostics import main


def test_startup_failure_creates_readable_escaped_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths.from_root(tmp_path / "data")
    monkeypatch.setenv("CATALYST_NO_BROWSER", "1")

    def fail() -> int:
        raise RuntimeError("port <unavailable>")

    assert main(fail, lambda: paths) == 1
    page = paths.runtime / "startup-error.html"
    content = page.read_text(encoding="utf-8")
    assert "本地服务未能启动" in content
    assert "port &lt;unavailable&gt;" in content
    assert "port <unavailable>" not in content


def test_startup_failure_uses_native_notifier_in_desktop_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = AppPaths.from_root(tmp_path / "data")
    monkeypatch.delenv("CATALYST_NO_WINDOW", raising=False)
    monkeypatch.delenv("CATALYST_NO_BROWSER", raising=False)
    notices: list[tuple[Path, str]] = []

    def fail() -> int:
        raise RuntimeError("webview unavailable")

    def notify(page: Path, error: Exception) -> bool:
        notices.append((page, str(error)))
        return True

    assert main(fail, lambda: paths, notify) == 1
    assert notices == [(paths.runtime / "startup-error.html", "webview unavailable")]


def test_shortcut_script_creates_a_windows_link_in_requested_directory(
    tmp_path: Path,
) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "install-shortcut.ps1"
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-DestinationDirectory",
            str(tmp_path),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert (tmp_path / "催化文献.lnk").is_file()
