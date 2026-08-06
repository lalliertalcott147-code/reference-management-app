from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

WINDOW_TITLE = "文献管理器"


def run_desktop_window(
    launch_url: str,
    *,
    storage_path: Path,
    on_closed: Callable[[], None],
    webview_module: Any | None = None,
) -> None:
    """Open the local UI in a native Windows WebView2 window.

    The import remains lazy so runtime probes and headless package tests do not
    initialize a GUI subsystem. The local FastAPI server is still the sole
    authority for data and session security.
    """

    webview = webview_module or importlib.import_module("webview")
    storage_path.mkdir(parents=True, exist_ok=True)

    # Keep the main UI inside the desktop shell. Explicit target=_blank links
    # (WoS, DOI and source records) retain their real URL in the system browser.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["REMOTE_DEBUGGING_PORT"] = None

    window = webview.create_window(
        WINDOW_TITLE,
        launch_url,
        width=1360,
        height=860,
        min_size=(1024, 680),
        resizable=True,
        background_color="#eef5f3",
        text_select=True,
        zoomable=False,
    )
    window.events.closed += on_closed
    webview.start(
        gui="edgechromium",
        debug=os.environ.get("CATALYST_DESKTOP_DEBUG") == "1",
        private_mode=False,
        storage_path=str(storage_path),
    )
