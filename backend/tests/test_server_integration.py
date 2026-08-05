from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import httpx2
import uvicorn
from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.launcher import bind_loopback_socket
from catalyst_literature.lifecycle import LifecycleMonitor
from catalyst_literature.security import SessionManager
from catalyst_literature.storage.database import DatabaseManager


def wait_until_started(server: uvicorn.Server, thread: threading.Thread) -> None:
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "Uvicorn did not start on the pre-bound loopback socket"


def test_production_frontend_and_authenticated_api_over_real_loopback(
    tmp_path: Path,
) -> None:
    static_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    assert (static_dir / "index.html").is_file(), "Build the production frontend first"

    bound: socket.socket = bind_loopback_socket()
    port = int(bound.getsockname()[1])
    origin = f"http://127.0.0.1:{port}"
    sessions = SessionManager()
    settings = AppSettings(paths=AppPaths.from_root(tmp_path / "data"))
    database = DatabaseManager(settings.paths)
    database.initialize()
    app = create_app(
        settings,
        origin=origin,
        sessions=sessions,
        static_dir=static_dir,
        database=database,
    )
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, lifespan="on")
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [bound]},
        daemon=True,
    )
    thread.start()
    try:
        wait_until_started(server, thread)
        with httpx2.Client(base_url=origin, follow_redirects=False, trust_env=False) as client:
            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["mode"] == "local-single-user"
            assert health.json()["database"] == "ready"

            root = client.get("/")
            assert root.status_code == 200
            assert '<div id="root"></div>' in root.text

            launch = client.get("/launch", params={"token": sessions.launch_token})
            assert launch.status_code == 303
            assert client.get("/api/session").json() == {"authenticated": True}

            forbidden = client.post(
                "/api/lifecycle/heartbeat",
                json={"tab_id": "integration_tab"},
                headers={"Origin": "http://not-the-app.invalid"},
            )
            assert forbidden.status_code == 403
            accepted = client.post(
                "/api/lifecycle/heartbeat",
                json={"tab_id": "integration_tab"},
                headers={"Origin": origin},
            )
            assert accepted.status_code == 200
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        bound.close()
        database.close()
    assert not thread.is_alive(), "The local server did not stop cleanly"


def test_lifecycle_runner_invokes_shutdown_once_after_idle() -> None:
    clock_value = [0.0]
    monitor = LifecycleMonitor(
        idle_shutdown_seconds=1,
        startup_grace_seconds=10,
        clock=lambda: clock_value[0],
    )
    monitor.heartbeat("tab")
    monitor.goodbye("tab")
    callback_count = 0

    async def scenario() -> None:
        nonlocal callback_count

        def shutdown() -> None:
            nonlocal callback_count
            callback_count += 1

        task = asyncio.create_task(monitor.run(shutdown, interval_seconds=0.001))
        clock_value[0] = 1.0
        await task

    asyncio.run(scenario())
    assert callback_count == 1
