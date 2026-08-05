from __future__ import annotations

import ctypes
import json
import os
import socket
import tempfile
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn

from .app import create_app
from .config import AppPaths, AppSettings
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


def open_existing(runtime_file: Path) -> bool:
    try:
        payload = json.loads(runtime_file.read_text(encoding="utf-8"))
        origin = str(payload["origin"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return webbrowser.open(origin)


def frontend_dist() -> Path:
    return resource_path("frontend", "dist")


def run() -> int:
    paths = AppPaths.default()
    paths.ensure()
    logger = configure_logging(paths)
    runtime_file = paths.runtime / "server.json"

    with SingleInstance() as instance:
        if not instance.is_primary:
            open_existing(runtime_file)
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
                atomic_json_write(
                    runtime_file,
                    {"pid": os.getpid(), "origin": origin, "started_at": time.time()},
                )
                launch_url = f"{origin}/launch?token={quote(sessions.launch_token)}"
                if os.environ.get("CATALYST_NO_BROWSER") != "1":
                    webbrowser.open(launch_url)
                server.run(sockets=[bound_socket])
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
