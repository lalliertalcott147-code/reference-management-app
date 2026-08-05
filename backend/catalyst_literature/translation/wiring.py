from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from ..config import AppPaths
from ..runtime_resources import resource_path
from ..storage.cache import CacheManager
from ..storage.database import DatabaseManager
from ..storage.jobs import JobRepository
from .model import HY_MT2_Q4_K_M, ModelInstaller
from .runtime import LlamaServerManager, LlamaTranslationEngine, ProcessOwner
from .service import GlossaryRepository, TranslationCoordinator, TranslationService


class TranslationRuntime:
    def __init__(
        self,
        *,
        database: DatabaseManager,
        paths: AppPaths,
        process_owner: ProcessOwner | None = None,
        executable: Path | None = None,
    ) -> None:
        core = database.require_core()
        cache_connection = database.require_cache()
        self.installer = ModelInstaller(HY_MT2_Q4_K_M, paths.models)
        self.manager = LlamaServerManager(
            executable=executable or _llama_executable(),
            model_path=HY_MT2_Q4_K_M.path_in(paths.models),
            manifest=HY_MT2_Q4_K_M,
            process_owner=process_owner,
        )
        self.jobs = JobRepository(core)
        self.glossary = GlossaryRepository(core)
        self.coordinator = TranslationCoordinator(
            TranslationService(
                core=core,
                cache=CacheManager(cache_connection, paths.cache),
                engine=LlamaTranslationEngine(self.manager),
                manifest=HY_MT2_Q4_K_M,
            ),
            self.jobs,
        )
        self.download_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="model-download"
        )

    def model_status(self) -> dict[str, object]:
        return {**self.installer.status(), "running": self.manager.running}

    def submit_download(self, *, confirmed: bool) -> int:
        if not confirmed:
            raise ValueError("下载 1.13 GB 模型前必须由用户明确确认")
        job_id = self.jobs.create(
            "model_download",
            f"model-download:{HY_MT2_Q4_K_M.sha256}",
            {"filename": HY_MT2_Q4_K_M.filename},
        )
        existing = self.jobs.get(job_id)
        if existing is not None and existing.status == "completed":
            return job_id

        def run() -> None:
            self.jobs.set_status(job_id, "running")
            try:
                path = self.installer.install(
                    confirmed=confirmed,
                    progress=lambda current, total: self.jobs.update_progress(
                        job_id, current, total
                    ),
                )
            except Exception as error:
                self.jobs.set_result(
                    job_id,
                    None,
                    error_code=type(error).__name__,
                    error_message=str(error),
                )
            else:
                self.jobs.set_result(job_id, {"path": str(path)})

        self.download_executor.submit(run)
        return job_id

    def job_payload(self, job_id: int) -> dict[str, object] | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        payload = asdict(job)
        live_result = self.coordinator.result_for(job_id)
        if live_result is not None:
            payload["result"] = live_result
        return payload

    def close(self) -> None:
        self.coordinator.close()
        self.download_executor.shutdown(wait=False, cancel_futures=True)
        self.manager.close()


def _llama_executable() -> Path:
    return resource_path("vendor", "llama.cpp", "llama-server.exe")
