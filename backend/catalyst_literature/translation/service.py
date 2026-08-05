from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

import apsw

from ..library import refresh_paper_fts
from ..storage.cache import CacheManager
from ..storage.database import require_row, utc_now
from ..storage.jobs import Job, JobRepository
from .model import ModelManifest
from .text import (
    BUILTIN_GLOSSARY,
    build_instruction,
    glossary_version,
    protect_text,
    split_segments,
)


class TranslationCancelled(RuntimeError):
    pass


class TranslationEngine(Protocol):
    def translate(self, text: str, instruction: str, *, timeout: float) -> str: ...


@dataclass(frozen=True)
class TranslationResult:
    paper_id: int
    field_name: str
    source_text: str
    translated_text: str
    saved: bool
    from_cache: bool
    model_version: str
    glossary_version: str


class GlossaryRepository:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    def translation_terms(self, *, include_builtin: bool = True) -> dict[str, str]:
        terms = dict(BUILTIN_GLOSSARY) if include_builtin else {}
        for term, mapped in self.connection.execute(
            "SELECT term, mapped_term FROM interest_terms WHERE term_type='glossary' ORDER BY id"
        ):
            if mapped:
                terms[str(term)] = str(mapped)
        return terms

    def protected_terms(self) -> list[str]:
        return [
            str(row[0])
            for row in self.connection.execute(
                "SELECT term FROM interest_terms WHERE term_type='do_not_translate' ORDER BY id"
            )
        ]

    def list_user_terms(self) -> list[dict[str, object]]:
        return [
            {"id": int(row[0]), "term": row[1], "mapped_term": row[2], "term_type": row[3]}
            for row in self.connection.execute(
                """
                SELECT id, term, mapped_term, term_type FROM interest_terms
                WHERE term_type IN ('glossary', 'do_not_translate') ORDER BY lower(term), id
                """
            )
        ]

    def add(self, term: str, mapped_term: str | None, term_type: str) -> int:
        cleaned = " ".join(term.split())
        mapped = None if mapped_term is None else " ".join(mapped_term.split())
        if not cleaned or term_type not in {"glossary", "do_not_translate"}:
            raise ValueError("术语内容或类型无效")
        if term_type == "glossary" and not mapped:
            raise ValueError("翻译术语必须填写中文译法")
        self.connection.execute(
            """
            INSERT INTO interest_terms(term, mapped_term, term_type, created_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(term, term_type) DO UPDATE SET mapped_term=excluded.mapped_term
            """,
            (cleaned, mapped, term_type, utc_now()),
        )
        row = require_row(
            self.connection.execute(
                "SELECT id FROM interest_terms WHERE term=? AND term_type=?",
                (cleaned, term_type),
            ).fetchone(),
            "reading glossary term",
        )
        return int(row[0])

    def delete(self, term_id: int) -> None:
        self.connection.execute(
            """
            DELETE FROM interest_terms
            WHERE id=? AND term_type IN ('glossary', 'do_not_translate')
            """,
            (term_id,),
        )


class TranslationService:
    def __init__(
        self,
        *,
        core: apsw.Connection,
        cache: CacheManager,
        engine: TranslationEngine,
        manifest: ModelManifest,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.core = core
        self.cache = cache
        self.engine = engine
        self.manifest = manifest
        self.clock = clock

    def translate(
        self,
        *,
        paper_id: int,
        field_name: str,
        save: bool,
        use_glossary: bool,
        cancelled: threading.Event,
        progress: Callable[[int, int], None],
        total_timeout: float = 300,
    ) -> TranslationResult:
        if field_name not in {"title", "abstract"}:
            raise ValueError("只支持翻译题名和摘要")
        source_text = self._source_text(paper_id, field_name)
        glossary_repo = GlossaryRepository(self.core)
        glossary = (
            glossary_repo.translation_terms(include_builtin=True) if use_glossary else {}
        )
        protected_terms = glossary_repo.protected_terms() if use_glossary else []
        glossary_id = glossary_version(glossary, protected_terms)
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        cache_key = ":".join(
            ("translation", source_hash, "zh", self.manifest.version, glossary_id)
        )
        persistent = self.core.execute(
            """
            SELECT translated_text FROM translations
            WHERE source_hash=? AND target_language='zh' AND model_version=?
              AND glossary_version=? ORDER BY id DESC LIMIT 1
            """,
            (source_hash, self.manifest.version, glossary_id),
        ).fetchone()
        cached = self.cache.get(cache_key)
        from_cache = persistent is not None or cached is not None
        if persistent is not None:
            translated = str(persistent[0])
        elif cached is not None:
            translated = cached.decode("utf-8")
        else:
            translated = self._run_segments(
                source_text,
                glossary,
                protected_terms,
                cancelled,
                progress,
                total_timeout,
            )
            self.cache.put("translation", cache_key, translated.encode("utf-8"))
        if cancelled.is_set():
            raise TranslationCancelled("翻译已取消, 原文未改动")
        if save:
            self.core.execute(
                """
                INSERT INTO translations(
                    paper_id, field_name, source_hash, target_language, model_version,
                    glossary_version, translated_text, created_at
                ) VALUES(?, ?, ?, 'zh', ?, ?, ?, ?)
                ON CONFLICT(source_hash, target_language, model_version, glossary_version)
                DO NOTHING
                """,
                (
                    paper_id,
                    field_name,
                    source_hash,
                    self.manifest.version,
                    glossary_id,
                    translated,
                    utc_now(),
                ),
            )
            if field_name == "title":
                self.core.execute("UPDATE papers SET title_zh=? WHERE id=?", (translated, paper_id))
            refresh_paper_fts(self.core, paper_id)
        return TranslationResult(
            paper_id,
            field_name,
            source_text,
            translated,
            save,
            from_cache,
            self.manifest.version,
            glossary_id,
        )

    def _source_text(self, paper_id: int, field_name: str) -> str:
        if field_name == "title":
            row = self.core.execute(
                "SELECT title_original FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        else:
            row = self.core.execute(
                """
                SELECT content FROM abstracts WHERE paper_id=?
                ORDER BY is_preferred DESC, id LIMIT 1
                """,
                (paper_id,),
            ).fetchone()
        if row is None or not str(row[0]).strip():
            raise ValueError("这篇文献没有可翻译的原文")
        return str(row[0])

    def _run_segments(
        self,
        source_text: str,
        glossary: dict[str, str],
        protected_terms: list[str],
        cancelled: threading.Event,
        progress: Callable[[int, int], None],
        total_timeout: float,
    ) -> str:
        protected = protect_text(source_text, protected_terms)
        segments = split_segments(protected.text)
        translated: list[str] = []
        started = self.clock()
        instruction = build_instruction(glossary)
        for index, segment in enumerate(segments):
            if cancelled.is_set():
                raise TranslationCancelled("翻译已取消, 原文未改动")
            remaining = total_timeout - (self.clock() - started)
            if remaining <= 0:
                raise TimeoutError("翻译超过五分钟, 已停止且保留原文")
            last_error: Exception | None = None
            for _attempt in range(2):
                try:
                    translated.append(
                        self.engine.translate(segment, instruction, timeout=min(90, remaining))
                    )
                except Exception as error:
                    last_error = error
                    continue
                break
            else:
                assert last_error is not None
                raise last_error
            progress(index + 1, len(segments))
        return protected.restore("".join(translated))


class TranslationCoordinator:
    def __init__(self, service: TranslationService, jobs: JobRepository) -> None:
        self.service = service
        self.jobs = jobs
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="translation")
        self._cancellations: dict[int, threading.Event] = {}
        self._futures: dict[int, Future[None]] = {}
        self._results: dict[int, dict[str, object]] = {}
        self._lock = threading.Lock()

    def submit(
        self, *, paper_id: int, field_name: str, save: bool, use_glossary: bool
    ) -> int:
        job_id = self.jobs.create(
            "translation",
            f"translation:{uuid.uuid4().hex}",
            {
                "paper_id": paper_id,
                "field_name": field_name,
                "save": save,
                "use_glossary": use_glossary,
            },
        )
        cancellation = threading.Event()
        with self._lock:
            self._cancellations[job_id] = cancellation
            self._futures[job_id] = self.executor.submit(
                self._run, job_id, paper_id, field_name, save, use_glossary, cancellation
            )
        return job_id

    def _run(
        self,
        job_id: int,
        paper_id: int,
        field_name: str,
        save: bool,
        use_glossary: bool,
        cancellation: threading.Event,
    ) -> None:
        if cancellation.is_set():
            self.jobs.set_status(job_id, "cancelled")
            return
        self.jobs.set_status(job_id, "running")
        try:
            result = self.service.translate(
                paper_id=paper_id,
                field_name=field_name,
                save=save,
                use_glossary=use_glossary,
                cancelled=cancellation,
                progress=lambda current, total: self.jobs.update_progress(job_id, current, total),
            )
        except TranslationCancelled:
            self.jobs.set_status(job_id, "cancelled")
        except Exception as error:
            self.jobs.set_result(
                job_id,
                None,
                error_code=type(error).__name__,
                error_message=str(error),
            )
        else:
            result_payload: dict[str, object] = result.__dict__
            with self._lock:
                self._results[job_id] = result_payload
            self.jobs.set_result(
                job_id,
                {
                    "paper_id": result.paper_id,
                    "field_name": result.field_name,
                    "saved": result.saved,
                    "from_cache": result.from_cache,
                    "model_version": result.model_version,
                    "glossary_version": result.glossary_version,
                },
            )

    def cancel(self, job_id: int) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.status not in {"pending", "running", "cancelling"}:
            return False
        with self._lock:
            cancellation = self._cancellations.get(job_id)
            future = self._futures.get(job_id)
        if cancellation is None:
            return False
        cancellation.set()
        self.jobs.set_status(job_id, "cancelling")
        if future is not None and future.cancel():
            self.jobs.set_status(job_id, "cancelled")
        return True

    def result_for(self, job_id: int) -> dict[str, object] | None:
        with self._lock:
            return self._results.get(job_id)

    def get(self, job_id: int) -> Job | None:
        return self.jobs.get(job_id)

    def close(self) -> None:
        with self._lock:
            for cancellation in self._cancellations.values():
                cancellation.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
