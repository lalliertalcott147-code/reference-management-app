from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from catalyst_literature.translation.model import ModelManifest
from catalyst_literature.translation.runtime import LlamaServerManager


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated += 1
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode or 0


class FakeOwner:
    def __init__(self) -> None:
        self.starts: list[list[str]] = []
        self.process = FakeProcess()

    def start(self, args: list[str], **kwargs: Any) -> FakeProcess:
        del kwargs
        self.starts.append(args)
        return self.process


def test_llama_server_starts_once_for_concurrent_requests_and_stops_idle(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"exe")
    manifest = ModelManifest(
        "repo", model.name, "https://huggingface.co/repo/model", 5,
        "9372c470eeadd5ecd9c3c74c2b3cb633f8e2f2fad799250a0f70d652b6b825e4",
        "v1", "Apache-2.0",
    )
    owner = FakeOwner()
    clock = [10.0]
    manager = LlamaServerManager(
        executable=executable,
        model_path=model,
        manifest=manifest,
        process_owner=owner,
        health_check=lambda _url: True,
        port_factory=lambda: 43123,
        idle_seconds=5,
        clock=lambda: clock[0],
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        urls = list(executor.map(lambda _index: manager.ensure_ready(), range(4)))
    assert urls == ["http://127.0.0.1:43123"] * 4
    assert len(owner.starts) == 1
    assert "--parallel" in owner.starts[0]
    assert owner.starts[0][owner.starts[0].index("--parallel") + 1] == "1"
    clock[0] = 16.0
    assert manager.stop_if_idle() is True
    assert owner.process.terminated == 1
