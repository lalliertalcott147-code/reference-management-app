from __future__ import annotations

from catalyst_literature.lifecycle import LifecycleMonitor


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_multiple_tabs_only_shutdown_after_last_tab_idle() -> None:
    clock = FakeClock()
    monitor = LifecycleMonitor(
        heartbeat_timeout_seconds=45,
        idle_shutdown_seconds=120,
        startup_grace_seconds=180,
        clock=clock,
    )
    monitor.heartbeat("tab-a")
    monitor.heartbeat("tab-b")
    monitor.goodbye("tab-a")
    clock.advance(200)
    monitor.heartbeat("tab-b")
    assert monitor.status().shutdown_due is False

    monitor.goodbye("tab-b")
    clock.advance(119.9)
    assert monitor.status().shutdown_due is False
    clock.advance(0.1)
    assert monitor.status().shutdown_due is True


def test_missing_heartbeat_expires_before_idle_timer() -> None:
    clock = FakeClock()
    monitor = LifecycleMonitor(
        heartbeat_timeout_seconds=45,
        idle_shutdown_seconds=120,
        clock=clock,
    )
    monitor.heartbeat("crashed-tab")
    clock.advance(45.1)
    status = monitor.status()
    assert status.active_tabs == 0
    assert status.shutdown_due is False
    clock.advance(120)
    assert monitor.status().shutdown_due is True


def test_startup_without_any_tab_eventually_exits() -> None:
    clock = FakeClock()
    monitor = LifecycleMonitor(startup_grace_seconds=180, clock=clock)
    clock.advance(179)
    assert monitor.status().shutdown_due is False
    clock.advance(1)
    assert monitor.status().shutdown_due is True
