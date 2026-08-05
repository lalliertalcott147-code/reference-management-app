from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    def __call__(self) -> float: ...


ShutdownCallback = Callable[[], None | Awaitable[None]]


@dataclass(frozen=True)
class LifecycleStatus:
    active_tabs: int
    had_tab: bool
    empty_for_seconds: float | None
    shutdown_due: bool


class LifecycleMonitor:
    def __init__(
        self,
        *,
        heartbeat_timeout_seconds: float = 45.0,
        idle_shutdown_seconds: float = 120.0,
        startup_grace_seconds: float = 180.0,
        clock: Clock = time.monotonic,
    ) -> None:
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.idle_shutdown_seconds = idle_shutdown_seconds
        self.startup_grace_seconds = startup_grace_seconds
        self.clock = clock
        self.started_at = clock()
        self._tabs: dict[str, float] = {}
        self._had_tab = False
        self._empty_since: float | None = None

    def heartbeat(self, tab_id: str) -> LifecycleStatus:
        if not tab_id.strip():
            raise ValueError("tab_id must not be empty")
        now = self.clock()
        self._tabs[tab_id] = now
        self._had_tab = True
        self._empty_since = None
        return self.status()

    def goodbye(self, tab_id: str) -> LifecycleStatus:
        self._tabs.pop(tab_id, None)
        self._prune()
        if self._had_tab and not self._tabs and self._empty_since is None:
            self._empty_since = self.clock()
        return self.status()

    def _prune(self) -> None:
        now = self.clock()
        expired = [
            tab_id
            for tab_id, seen_at in self._tabs.items()
            if now - seen_at > self.heartbeat_timeout_seconds
        ]
        for tab_id in expired:
            del self._tabs[tab_id]
        if self._had_tab and not self._tabs and self._empty_since is None:
            self._empty_since = now

    def status(self) -> LifecycleStatus:
        self._prune()
        now = self.clock()
        empty_for = None if self._empty_since is None else max(0.0, now - self._empty_since)
        if self._had_tab:
            shutdown_due = empty_for is not None and empty_for >= self.idle_shutdown_seconds
        else:
            shutdown_due = now - self.started_at >= self.startup_grace_seconds
        return LifecycleStatus(
            active_tabs=len(self._tabs),
            had_tab=self._had_tab,
            empty_for_seconds=empty_for,
            shutdown_due=shutdown_due,
        )

    async def run(
        self,
        on_shutdown: ShutdownCallback,
        *,
        interval_seconds: float = 1.0,
    ) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            if self.status().shutdown_due:
                result = on_shutdown()
                if inspect.isawaitable(result):
                    await result
                return
