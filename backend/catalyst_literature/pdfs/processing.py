from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Protocol, cast

import apsw

from ..storage.database import transaction, utc_now
from ..storage.jobs import JobRepository
from ..translation.runtime import DirectProcessOwner, ProcessOwner, _unwrap


class AnalysisRunner(Protocol):
    def run(
        self,
        path: Path,
        job_id: int,
        cancelled: threading.Event,
        progress: Callable[[int, int], None],
    ) -> dict[str, object]: ...


class PdfWorkerRunner:
    def __init__(
        self,
        runtime: Path,
        process_owner: ProcessOwner | None = None,
        ocr_home: Path | None = None,
    ) -> None:
        self.runtime = runtime.resolve()
        self.ocr_home = (ocr_home or runtime / "ocr-home").resolve()
        self.process_owner = process_owner or DirectProcessOwner()

    def run(
        self,
        path: Path,
        job_id: int,
        cancelled: threading.Event,
        progress: Callable[[int, int], None],
    ) -> dict[str, object]:
        output = self.runtime / f"pdf-job-{job_id}.json"
        cancel_file = self.runtime / f"pdf-job-{job_id}.cancel"
        progress_file = self.runtime / f"pdf-job-{job_id}.progress"
        output.unlink(missing_ok=True)
        cancel_file.unlink(missing_ok=True)
        progress_file.unlink(missing_ok=True)
        environment = os.environ.copy()
        backend_root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (backend_root, environment.get("PYTHONPATH", "")))
        )
        process = self.process_owner.start(
            _worker_command(
                [
                "--mode",
                "analyze",
                "--input",
                str(path),
                "--output",
                str(output),
                "--runtime-home",
                str(self.ocr_home),
                "--cancel-file",
                str(cancel_file),
                "--progress-file",
                str(progress_file),
                ]
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
        raw = _unwrap(process)
        last_progress = ""
        try:
            while raw.poll() is None:
                if cancelled.is_set():
                    cancel_file.touch()
                if progress_file.exists():
                    current_progress = progress_file.read_text(encoding="ascii")
                    if current_progress != last_progress:
                        current, total = current_progress.split(",", maxsplit=1)
                        progress(int(current), int(total))
                        last_progress = current_progress
                time.sleep(0.05)
            if raw.wait(timeout=5) != 0:
                if cancelled.is_set():
                    raise InterruptedError("PDF 处理已取消")
                raise RuntimeError("PDF/OCR 隔离工作进程失败")
            parsed = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise RuntimeError("PDF worker returned an invalid result")
            return cast(dict[str, object], parsed)
        finally:
            output.unlink(missing_ok=True)
            cancel_file.unlink(missing_ok=True)
            progress_file.unlink(missing_ok=True)

    def inspect(self, path: Path) -> tuple[int, list[dict[str, object]]]:
        token = uuid.uuid4().hex
        output = self.runtime / f"pdf-inspect-{token}.json"
        output.unlink(missing_ok=True)
        environment = os.environ.copy()
        backend_root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (backend_root, environment.get("PYTHONPATH", "")))
        )
        process = self.process_owner.start(
            _worker_command(
                [
                    "--mode",
                    "inspect",
                    "--input",
                    str(path),
                    "--output",
                    str(output),
                ]
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
        raw = _unwrap(process)
        try:
            try:
                exit_code = raw.wait(timeout=30)
            except subprocess.TimeoutExpired as error:
                raw.kill()
                raw.wait(timeout=5)
                raise RuntimeError("PDF 安全检查超时") from error
            if exit_code != 0 or not output.is_file():
                raise RuntimeError("PDF 安全检查隔离进程失败")
            payload = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("PDF 安全检查返回了无效结果")
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("error", "PDF 无法读取")))
            candidates = payload.get("candidates", [])
            if not isinstance(candidates, list):
                raise RuntimeError("PDF 安全检查候选数据无效")
            return int(str(payload["page_count"])), cast(list[dict[str, object]], candidates)
        finally:
            output.unlink(missing_ok=True)


def _worker_command(arguments: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pdf-worker", *arguments]
    return [sys.executable, "-m", "catalyst_literature.pdfs.worker", *arguments]


class PdfProcessingCoordinator:
    def __init__(
        self,
        connection: apsw.Connection,
        runner: AnalysisRunner,
    ) -> None:
        self.connection = connection
        self.runner = runner
        self.jobs = JobRepository(connection)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-processing")
        self._cancellations: dict[int, threading.Event] = {}
        self._futures: dict[int, Future[None]] = {}
        self._lock = threading.Lock()

    def submit(self, file_id: int, path: Path) -> int:
        job_id = self.jobs.create(
            "pdf_processing",
            f"pdf:{file_id}:{uuid.uuid4().hex}",
            {"file_id": file_id},
        )
        self._queue(job_id, file_id, path)
        return job_id

    def resume(self, job_id: int, file_id: int, path: Path) -> None:
        self._queue(job_id, file_id, path)

    def _queue(self, job_id: int, file_id: int, path: Path) -> None:
        cancellation = threading.Event()
        with self._lock:
            self._cancellations[job_id] = cancellation
            self._futures[job_id] = self.executor.submit(
                self._run, job_id, file_id, path, cancellation
            )

    def _run(
        self, job_id: int, file_id: int, path: Path, cancellation: threading.Event
    ) -> None:
        self.jobs.set_status(job_id, "running")
        try:
            result = self.runner.run(
                path,
                job_id,
                cancellation,
                lambda current, total: self.jobs.update_progress(job_id, current, total),
            )
            if cancellation.is_set():
                raise InterruptedError("PDF 处理已取消")
            self._persist(file_id, result)
        except InterruptedError:
            self.jobs.set_status(job_id, "cancelled")
        except Exception as error:
            self.jobs.set_result(
                job_id,
                None,
                error_code=type(error).__name__,
                error_message=str(error),
            )
        else:
            page_source = result.get("pages", [])
            pages = page_source if isinstance(page_source, list) else []
            scanned = sum(
                1 for page in pages if isinstance(page, dict) and page.get("source") == "ocr"
            )
            self.jobs.set_result(
                job_id,
                {"file_id": file_id, "pages": len(pages), "ocr_pages": scanned},
            )

    def _persist(self, file_id: int, result: dict[str, object]) -> None:
        page_source = result.get("pages", [])
        candidate_source = result.get("candidates", [])
        pages = page_source if isinstance(page_source, list) else []
        candidates = candidate_source if isinstance(candidate_source, list) else []
        with transaction(self.connection):
            self.connection.execute("DELETE FROM pdf_pages WHERE file_id=?", (file_id,))
            self.connection.execute(
                "DELETE FROM pdf_metadata_candidates WHERE file_id=?", (file_id,)
            )
            for page in pages:
                if not isinstance(page, dict):
                    continue
                self.connection.execute(
                    """
                    INSERT INTO pdf_pages(
                        file_id, page_number, width, height, classification,
                        text_source, content, blocks_json, confidence, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        page["page_number"],
                        page["width"],
                        page["height"],
                        page["classification"],
                        page["source"],
                        page["text"],
                        json.dumps(page["blocks"], ensure_ascii=False),
                        page["confidence"],
                        utc_now(),
                    ),
                )
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                self.connection.execute(
                    """
                    INSERT INTO pdf_metadata_candidates(
                        file_id, field_name, candidate_value, page_number,
                        evidence_text, method, confidence, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        candidate["field_name"],
                        candidate["value"],
                        candidate["page_number"],
                        candidate["evidence"],
                        candidate["method"],
                        candidate["confidence"],
                        utc_now(),
                    ),
                )

    def cancel(self, job_id: int) -> bool:
        with self._lock:
            cancellation = self._cancellations.get(job_id)
        if cancellation is None:
            return False
        cancellation.set()
        self.jobs.set_status(job_id, "cancelling")
        return True

    def close(self) -> None:
        with self._lock:
            for cancellation in self._cancellations.values():
                cancellation.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
