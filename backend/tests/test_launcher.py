from __future__ import annotations

import json
import uuid
from pathlib import Path

from catalyst_literature.launcher import SingleInstance, atomic_json_write, bind_loopback_socket


def test_bound_socket_is_loopback_and_uses_random_port() -> None:
    first = bind_loopback_socket()
    second = bind_loopback_socket()
    try:
        assert first.getsockname()[0] == "127.0.0.1"
        assert second.getsockname()[0] == "127.0.0.1"
        assert first.getsockname()[1] > 0
        assert first.getsockname()[1] != second.getsockname()[1]
    finally:
        first.close()
        second.close()


def test_named_mutex_allows_only_one_primary_instance() -> None:
    name = f"Local\\CatalystLiteratureTest-{uuid.uuid4()}"
    first = SingleInstance(name)
    second = SingleInstance(name)
    try:
        assert first.is_primary is True
        assert second.is_primary is False
    finally:
        second.close()
        first.close()
    third = SingleInstance(name)
    try:
        assert third.is_primary is True
    finally:
        third.close()


def test_atomic_runtime_state_never_leaves_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "server.json"
    atomic_json_write(target, {"pid": 123, "origin": "http://127.0.0.1:4567"})
    assert json.loads(target.read_text(encoding="utf-8"))["pid"] == 123
    assert list(target.parent.glob("*.tmp")) == []
