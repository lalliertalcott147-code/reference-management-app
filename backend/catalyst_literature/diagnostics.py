from __future__ import annotations

import html
import os
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path

from .config import AppPaths
from .launcher import run


def write_startup_diagnostic(paths: AppPaths, error: Exception) -> Path:
    paths.ensure()
    target = paths.runtime / "startup-error.html"
    message = html.escape(str(error) or type(error).__name__)
    target.write_text(
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        "<title>催化文献启动失败</title>"
        "<style>body{font:16px system-ui;max-width:720px;margin:64px auto;padding:24px}"
        "code{display:block;padding:16px;background:#f4f7f6;border-radius:8px}</style>"
        "<h1>本地服务未能启动</h1>"
        "<p>请确认数据目录可写、磁盘空间充足, 然后重新打开快捷方式。</p>"
        f"<code>{message}</code></html>",
        encoding="utf-8",
    )
    return target


def main(
    runner: Callable[[], int] = run,
    paths_factory: Callable[[], AppPaths] = AppPaths.default,
) -> int:
    try:
        return runner()
    except Exception as error:
        try:
            page = write_startup_diagnostic(paths_factory(), error)
            if os.environ.get("CATALYST_NO_BROWSER") != "1":
                webbrowser.open(page.as_uri())
            print(f"Catalyst Literature failed to start. Details: {page}", file=sys.stderr)
        except Exception:
            print(f"Catalyst Literature failed to start: {error}", file=sys.stderr)
        return 1
