from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from catalyst_literature.desktop import WINDOW_TITLE, run_desktop_window


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list[Callable[[], None]] = []

    def __iadd__(self, handler: Callable[[], None]) -> FakeEvent:
        self.handlers.append(handler)
        return self


class FakeEvents:
    def __init__(self) -> None:
        self.closed = FakeEvent()


class FakeWindow:
    def __init__(self) -> None:
        self.events = FakeEvents()


class FakeWebview:
    def __init__(self) -> None:
        self.settings: dict[str, Any] = {}
        self.window = FakeWindow()
        self.created: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.started: dict[str, Any] | None = None

    def create_window(self, *args: Any, **kwargs: Any) -> FakeWindow:
        self.created = (args, kwargs)
        return self.window

    def start(self, **kwargs: Any) -> None:
        self.started = kwargs


def test_desktop_window_uses_webview2_and_persistent_app_storage(tmp_path: Path) -> None:
    fake = FakeWebview()
    closed: list[bool] = []
    storage = tmp_path / "webview"

    run_desktop_window(
        "http://127.0.0.1:4321/launch?token=secret",
        storage_path=storage,
        on_closed=lambda: closed.append(True),
        webview_module=fake,
    )

    assert storage.is_dir()
    assert fake.created is not None
    args, options = fake.created
    assert args[:2] == (WINDOW_TITLE, "http://127.0.0.1:4321/launch?token=secret")
    assert options["min_size"] == (1024, 680)
    assert options["text_select"] is True
    assert fake.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True
    assert fake.settings["ALLOW_DOWNLOADS"] is True
    assert fake.settings["ALLOW_FILE_URLS"] is False
    assert fake.started == {
        "gui": "edgechromium",
        "debug": False,
        "private_mode": False,
        "storage_path": str(storage),
    }

    assert len(fake.window.events.closed.handlers) == 1
    fake.window.events.closed.handlers[0]()
    assert closed == [True]
