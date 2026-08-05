from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data: Path
    library: Path
    models: Path
    backups: Path
    logs: Path
    runtime: Path
    cache: Path

    @classmethod
    def from_root(cls, root: Path) -> AppPaths:
        resolved = root.expanduser().resolve()
        return cls(
            root=resolved,
            data=resolved / "data",
            library=resolved / "library",
            models=resolved / "models",
            backups=resolved / "backups",
            logs=resolved / "logs",
            runtime=resolved / "runtime",
            cache=resolved / "cache",
        )

    @classmethod
    def default(cls) -> AppPaths:
        explicit = os.environ.get("CATALYST_DATA_DIR")
        if explicit:
            return cls.from_root(Path(explicit))
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is unavailable on this Windows account")
        return cls.from_root(Path(local_app_data) / "CatalystLiterature")

    def ensure(self) -> None:
        for path in (
            self.root,
            self.data,
            self.library / "pdfs",
            self.models,
            self.backups,
            self.logs,
            self.runtime,
            self.cache,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class AppSettings:
    paths: AppPaths
    host: str = "127.0.0.1"
    heartbeat_timeout_seconds: float = 45.0
    idle_shutdown_seconds: float = 120.0
    startup_grace_seconds: float = 180.0
    monitor_interval_seconds: float = 1.0
