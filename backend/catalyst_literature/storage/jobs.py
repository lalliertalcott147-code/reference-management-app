from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import apsw

from .database import require_row, utc_now


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    idempotency_key: str
    status: str
    progress_current: int
    progress_total: int | None
    retry_count: int
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None


class JobRepository:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    def create(self, kind: str, idempotency_key: str, payload: dict[str, Any]) -> int:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO jobs(kind, idempotency_key, status, payload_json, created_at, updated_at)
            VALUES(?, ?, 'pending', ?, ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (kind, idempotency_key, json.dumps(payload, ensure_ascii=False), now, now),
        )
        row = self.connection.execute(
            "SELECT id FROM jobs WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if row is None:
            raise RuntimeError("Job insert did not produce a row")
        return int(row[0])

    def update_progress(self, job_id: int, current: int, total: int | None) -> None:
        if current < 0 or (total is not None and (total < 0 or current > total)):
            raise ValueError("Invalid job progress")
        self.connection.execute(
            """
            UPDATE jobs SET progress_current=?, progress_total=?, updated_at=?
            WHERE id=? AND status IN ('pending', 'running')
            """,
            (current, total, utc_now(), job_id),
        )

    def set_status(self, job_id: int, status: str, *, error_code: str | None = None) -> None:
        allowed = {"pending", "running", "cancelling", "cancelled", "completed", "failed"}
        if status not in allowed:
            raise ValueError(f"Unsupported job status: {status}")
        self.connection.execute(
            "UPDATE jobs SET status=?, error_code=?, updated_at=? WHERE id=?",
            (status, error_code, utc_now(), job_id),
        )

    def set_result(
        self,
        job_id: int,
        result: dict[str, Any] | None,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        status = "completed" if error_code is None else "failed"
        payload = None if result is None else json.dumps(result, ensure_ascii=False)
        self.connection.execute(
            """
            UPDATE jobs SET status=?, result_json=?, error_code=?,
                payload_json=json_set(payload_json, '$.error_message', ?), updated_at=?
            WHERE id=?
            """,
            (status, payload, error_code, error_message, utc_now(), job_id),
        )

    def recover_interrupted(self, *, max_retries: int = 3) -> tuple[int, int]:
        now = utc_now()
        recoverable_row = require_row(
            self.connection.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('running', 'cancelling') "
                "AND retry_count < ?",
                (max_retries,),
            ).fetchone(),
            "counting recoverable jobs",
        )
        recoverable = int(recoverable_row[0])
        failed_row = require_row(
            self.connection.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('running', 'cancelling') "
                "AND retry_count >= ?",
                (max_retries,),
            ).fetchone(),
            "counting failed jobs",
        )
        failed = int(failed_row[0])
        self.connection.execute(
            """
            UPDATE jobs SET status='pending', retry_count=retry_count+1,
                error_code='interrupted', updated_at=?
            WHERE status IN ('running', 'cancelling') AND retry_count < ?
            """,
            (now, max_retries),
        )
        self.connection.execute(
            """
            UPDATE jobs SET status='failed', error_code='retry_limit', updated_at=?
            WHERE status IN ('running', 'cancelling') AND retry_count >= ?
            """,
            (now, max_retries),
        )
        return recoverable, failed

    def get(self, job_id: int) -> Job | None:
        row = self.connection.execute(
            """
            SELECT id, kind, idempotency_key, status, progress_current,
                   progress_total, retry_count, result_json, error_code,
                   json_extract(payload_json, '$.error_message')
            FROM jobs WHERE id=?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        values = list(row)
        values[7] = None if values[7] is None else json.loads(str(values[7]))
        return Job(*values)
