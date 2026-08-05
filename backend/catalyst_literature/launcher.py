from __future__ import annotations

import ctypes
import json
import os
import socket
import tempfile
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn

from .app import create_app
from .config import AppPaths, AppSettings
from .desktop import run_desktop_window
from .logging_setup import configure_logging
from .processes import ChildProcessJob
from .runtime_resources import resource_path
from .security import SessionManager
from .storage.database import DatabaseManager
from .storage.jobs import JobRepository

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, name: str = "Local\\CatalystLiteratureApp") -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel32 = kernel32
        self._handle = kernel32.CreateMutexW(None, False, name)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.is_primary = ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> SingleInstance:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def bind_loopback_socket(host: str = "127.0.0.1") -> socket.socket:
    bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bound.bind((host, 0))
    bound.listen(2048)
    return bound


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def focus_process_window(pid: int) -> bool:
    """Restore and focus the visible top-level window owned by ``pid``."""

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    matches: list[int] = []

    def visit(window: int, _parameter: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(window), ctypes.byref(process_id))
        if process_id.value == pid and user32.IsWindowVisible(wintypes.HWND(window)):
            matches.append(window)
            return False
        return True

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    if not matches:
        return False
    window = wintypes.HWND(matches[0])
    user32.ShowWindow(window, 9)  # SW_RESTORE
    user32.SetForegroundWindow(window)
    return True


def focus_existing(
    runtime_file: Path,
    focus: Callable[[int], bool] | None = None,
) -> bool:
    try:
        payload = json.loads(runtime_file.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if pid <= 0:
        return False
    return (focus or focus_process_window)(pid)


def open_existing(runtime_file: Path) -> bool:
    """Backward-compatible name for focusing the single desktop instance."""

    return focus_existing(runtime_file)


def wait_for_server(
    server: uvicorn.Server,
    thread: threading.Thread,
    failures: list[BaseException],
    *,
    timeout_seconds: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not server.started:
        if failures:
            raise RuntimeError("The local server failed during startup") from failures[0]
        if not thread.is_alive():
            raise RuntimeError("The local server stopped during startup")
        if time.monotonic() >= deadline:
            raise TimeoutError("The local server did not become ready in time")
        time.sleep(0.05)


def frontend_dist() -> Path:
    return resource_path("frontend", "dist")


def run() -> int:
    paths = AppPaths.default()
    paths.ensure()
    logger = configure_logging(paths)
    runtime_file = paths.runtime / "server.json"

    with SingleInstance() as instance:
        if not instance.is_primary:
            for _attempt in range(20):
                if focus_existing(runtime_file):
                    break
                time.sleep(0.1)
            return 0

        bound_socket = bind_loopback_socket()
        port = int(bound_socket.getsockname()[1])
        origin = f"http://127.0.0.1:{port}"
        sessions = SessionManager()
        database = DatabaseManager(paths)
        database.initialize()
        recovered, failed = JobRepository(database.require_core()).recover_interrupted()
        logger.info("startup jobs_recovered=%s jobs_failed=%s", recovered, failed)
        server_holder: dict[str, uvicorn.Server] = {}

        def request_shutdown() -> None:
            server = server_holder.get("server")
            if server:
                server.should_exit = True

        settings = AppSettings(
            paths=paths,
            heartbeat_timeout_seconds=float(
                os.environ.get("CATALYST_HEARTBEAT_TIMEOUT_SECONDS", "45")
            ),
            idle_shutdown_seconds=float(
                os.environ.get("CATALYST_IDLE_SHUTDOWN_SECONDS", "120")
            ),
            startup_grace_seconds=float(
                os.environ.get("CATALYST_STARTUP_GRACE_SECONDS", "180")
            ),
            monitor_interval_seconds=float(
                os.environ.get("CATALYST_MONITOR_INTERVAL_SECONDS", "1")
            ),
        )
        try:
            with ChildProcessJob() as child_processes:
                application = create_app(
                    settings,
                    origin=origin,
                    sessions=sessions,
                    on_shutdown=request_shutdown,
                    static_dir=frontend_dist(),
                    database=database,
                    child_processes=child_processes,
                )
                config = uvicorn.Config(
                    application,
                    host=settings.host,
                    port=port,
                    log_level="info",
                    access_log=False,
                    log_config=None,
                )
                server = uvicorn.Server(config)
                server_holder["server"] = server
                launch_url = f"{origin}/launch?token={quote(sessions.launch_token)}"
                runtime_payload = {
                    "pid": os.getpid(),
                    "origin": origin,
                    "started_at": time.time(),
                    "window_mode": "desktop",
                }
                headless = (
                    os.environ.get("CATALYST_NO_WINDOW") == "1"
                    or os.environ.get("CATALYST_NO_BROWSER") == "1"
                )
                if headless:
                    runtime_payload["window_mode"] = "headless"
                    atomic_json_write(runtime_file, runtime_payload)
                    server.run(sockets=[bound_socket])
                else:
                    failures: list[BaseException] = []

                    def serve() -> None:
                        try:
                            server.run(sockets=[bound_socket])
                        except BaseException as error:
                            failures.append(error)

                    server_thread = threading.Thread(
                        target=serve,
                        name="catalyst-local-server",
                        daemon=True,
                    )
                    server_thread.start()
                    try:
                        wait_for_server(server, server_thread, failures)
                        atomic_json_write(runtime_file, runtime_payload)
                        run_desktop_window(
                            launch_url,
                            storage_path=paths.root / "webview",
                            on_closed=request_shutdown,
                        )
                    finally:
                        request_shutdown()
                        server_thread.join(timeout=15)
                        if server_thread.is_alive():
                            server.force_exit = True
                            server_thread.join(timeout=5)
                        if server_thread.is_alive():
                            raise RuntimeError("The local server did not stop with the window")
                    if failures:
                        raise RuntimeError("The local server stopped unexpectedly") from failures[0]
        finally:
            bound_socket.close()
            database.close()
            try:
                current = json.loads(runtime_file.read_text(encoding="utf-8"))
                if current.get("pid") == os.getpid():
                    runtime_file.unlink(missing_ok=True)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
    return 0
