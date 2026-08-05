from __future__ import annotations

from ..config import AppPaths
from ..storage.database import DatabaseManager
from ..translation.runtime import ProcessOwner
from .ingest import PdfIngestService
from .processing import PdfProcessingCoordinator, PdfWorkerRunner


class PdfRuntime:
    def __init__(
        self,
        database: DatabaseManager,
        paths: AppPaths,
        process_owner: ProcessOwner | None = None,
    ) -> None:
        runner = PdfWorkerRunner(paths.runtime, process_owner, paths.models / "ocr")
        self.ingest = PdfIngestService(database.require_core(), paths, runner)
        self.processing = PdfProcessingCoordinator(
            database.require_core(), runner
        )
        self.ingest.cleanup_expired()
        self._resume_pending(database)

    def _resume_pending(self, database: DatabaseManager) -> None:
        core = database.require_core()
        rows = core.execute(
            """
            SELECT j.id, json_extract(j.payload_json, '$.file_id')
            FROM jobs j WHERE j.kind='pdf_processing' AND j.status='pending'
            """
        ).fetchall()
        for job_id, file_id in rows:
            if file_id is None:
                self.processing.jobs.set_result(
                    int(str(job_id)), None, error_code="missing_file_id"
                )
                continue
            try:
                path = self.ingest.path_for_file(int(str(file_id)))
            except Exception as error:
                self.processing.jobs.set_result(
                    int(str(job_id)),
                    None,
                    error_code=type(error).__name__,
                    error_message=str(error),
                )
            else:
                self.processing.resume(int(str(job_id)), int(str(file_id)), path)

    def close(self) -> None:
        self.processing.close()
