from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from .config import AppPaths

SENSITIVE_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|token|password|cookie)\b\s*[:=]\s*([^\s,;]+)"
)


def redact(message: str) -> str:
    return SENSITIVE_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(paths: AppPaths) -> logging.Logger:
    paths.logs.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("catalyst_literature")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(
        paths.logs / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return logger


def diagnostic_manifest(paths: AppPaths) -> dict[str, object]:
    logs = [
        {"name": path.name, "bytes": path.stat().st_size}
        for path in sorted(paths.logs.glob("app.log*"))
        if path.is_file()
    ]
    return {
        "data_directory": str(paths.root),
        "logs": logs,
        "included": ["rotating logs", "database integrity status", "version information"],
        "excluded": [
            "API keys",
            "session tokens",
            "PDF contents",
            "abstract contents",
            "note contents",
        ],
    }
