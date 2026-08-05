from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import URLError
from urllib.request import Request, urlopen

from .model import ModelManifest


class ProcessLike(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class ProcessOwner(Protocol):
    def start(self, args: list[str], **kwargs: Any) -> Any: ...


class DirectProcessOwner:
    def start(self, args: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        return subprocess.Popen(args, **kwargs)


def _unwrap(process: Any) -> ProcessLike:
    value = process.process if hasattr(process, "process") else process
    return cast(ProcessLike, value)


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
        bound.bind(("127.0.0.1", 0))
        return int(bound.getsockname()[1])


def _default_health(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.5) as response:
            return int(response.status) == 200
    except (OSError, URLError):
        return False


class LlamaServerManager:
    def __init__(
        self,
        *,
        executable: Path,
        model_path: Path,
        manifest: ModelManifest,
        process_owner: ProcessOwner | None = None,
        health_check: Callable[[str], bool] = _default_health,
        port_factory: Callable[[], int] = _available_port,
        startup_timeout: float = 90.0,
        idle_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.executable = executable
        self.model_path = model_path
        self.manifest = manifest
        self.process_owner = process_owner or DirectProcessOwner()
        self.health_check = health_check
        self.port_factory = port_factory
        self.startup_timeout = startup_timeout
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.sleeper = sleeper
        self._lock = threading.Lock()
        self._process: Any | None = None
        self._base_url: str | None = None
        self._last_used = 0.0

    @property
    def running(self) -> bool:
        process = None if self._process is None else _unwrap(self._process)
        return process is not None and process.poll() is None

    def ensure_ready(self) -> str:
        with self._lock:
            if self.running and self._base_url and self.health_check(f"{self._base_url}/health"):
                self._last_used = self.clock()
                return self._base_url
            self._stop_locked()
            self.manifest.verify(self.model_path)
            if not self.executable.is_file():
                raise RuntimeError("llama.cpp 本地运行器缺失")
            port = self.port_factory()
            base_url = f"http://127.0.0.1:{port}"
            threads = max(1, (os.cpu_count() or 2) - 1)
            self._process = self.process_owner.start(
                [
                    str(self.executable),
                    "--model",
                    str(self.model_path),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--ctx-size",
                    "4096",
                    "--parallel",
                    "1",
                    "--threads",
                    str(threads),
                    "--no-webui",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._base_url = base_url
            deadline = self.clock() + self.startup_timeout
            while self.clock() < deadline:
                process = _unwrap(self._process)
                if process.poll() is not None:
                    self._stop_locked()
                    raise RuntimeError("本地翻译模型启动失败")
                if self.health_check(f"{base_url}/health"):
                    self._last_used = self.clock()
                    return base_url
                self.sleeper(0.1)
            self._stop_locked()
            raise TimeoutError("本地翻译模型启动超时")

    def touch(self) -> None:
        with self._lock:
            self._last_used = self.clock()

    def stop_if_idle(self) -> bool:
        with self._lock:
            if self.running and self.clock() - self._last_used >= self.idle_seconds:
                self._stop_locked()
                return True
            return False

    def close(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._process is not None:
            process = _unwrap(self._process)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self._process = None
        self._base_url = None


@dataclass
class LlamaTranslationEngine:
    manager: LlamaServerManager

    def translate(self, text: str, instruction: str, *, timeout: float) -> str:
        base_url = self.manager.ensure_ready()
        payload = json.dumps(
            {
                "model": "local-model",
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.1,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            parsed: Mapping[str, Any] = json.loads(response.read().decode("utf-8"))
        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("本地翻译模型返回了无效结果")
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise RuntimeError("本地翻译模型没有返回译文")
        self.manager.touch()
        return str(message["content"]).strip()
