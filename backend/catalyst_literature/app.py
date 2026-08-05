from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

import apsw
from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .api_models import (
    EnabledRequest,
    ExportRequest,
    GlossaryTermRequest,
    InterestTermRequest,
    JournalSubscriptionRequest,
    LibraryCreateRequest,
    LibraryPaperAddRequest,
    LibraryWorkspaceCardCreate,
    LibraryWorkspaceCardUpdate,
    LibraryWorkspaceRequest,
    ModelDownloadRequest,
    NoteAppendRequest,
    NoteSaveRequest,
    PaperStateRequest,
    PdfAnnotationRequest,
    PdfAnnotationUpdate,
    PdfConfirmRequest,
    PdfMetadataUpdate,
    PdfReadingPositionRequest,
    ResearchTopicRequest,
    SavedSearchRequest,
    SavePaperRequest,
    SettingsUpdate,
    TagRequest,
    TextTranslationRequest,
    TranslationRequest,
)
from .config import AppSettings
from .importers.models import ImportValidationError
from .importers.service import WosImportService
from .importers.validation import MAX_IMPORT_BYTES
from .library import LibraryService, refresh_paper_fts
from .lifecycle import LifecycleMonitor, ShutdownCallback
from .pdfs.analysis import PdfAnalysisError
from .pdfs.ingest import MAX_PDF_BYTES, PdfUploadError, new_upload_token
from .pdfs.reader import PdfReaderService
from .pdfs.wiring import PdfRuntime
from .profile import MAX_AVATAR_BYTES, AvatarError, AvatarStore
from .search.merge import merge_records
from .search.models import PaperRecord, SearchQuery
from .search.persistence import SearchResultRepository
from .search.service import SearchService
from .search.wiring import build_search_service
from .security import SESSION_COOKIE, LocalSessionMiddleware, SessionManager
from .storage.database import (
    DatabaseManager,
    StorageError,
    require_row,
    transaction,
    utc_now,
)
from .storage.repositories import SettingsRepository
from .storage.secrets import SecretStore
from .translation.wiring import TranslationRuntime
from .updates import (
    AlertService,
    PreferenceService,
    RecommendationService,
    UpdateService,
    serialize_recommendations,
)


class TabMessage(BaseModel):
    tab_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class SearchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    field: Literal["topic", "title", "author", "doi"] = "topic"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)
    cursor: str | None = None
    year_from: int | None = Field(default=None, ge=1600, le=2200)
    year_to: int | None = Field(default=None, ge=1600, le=2200)
    sort: str = "relevance"
    refresh: bool = False


def _apply_pdf_metadata(
    connection: apsw.Connection, file_id: int, request: PdfMetadataUpdate
) -> None:
    values: dict[str, object] = {
        key: value
        for key, value in {
            "title": request.title,
            "abstract": request.abstract,
            "doi": request.doi,
            "authors": request.authors,
            "year": request.year,
        }.items()
        if value is not None
    }
    with transaction(connection):
        if request.title is not None:
            connection.execute(
                "UPDATE papers SET title_original=?, updated_at=? WHERE id=?",
                (request.title.strip(), utc_now(), request.paper_id),
            )
        if request.doi is not None:
            doi = request.doi.strip().lower()
            for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
                if doi.startswith(prefix):
                    doi = doi[len(prefix) :]
            connection.execute(
                "UPDATE papers SET doi=?, updated_at=? WHERE id=?",
                (doi or None, utc_now(), request.paper_id),
            )
        if request.year is not None:
            connection.execute(
                "UPDATE papers SET publication_year=?, updated_at=? WHERE id=?",
                (request.year, utc_now(), request.paper_id),
            )
        if request.abstract is not None:
            abstract = request.abstract.strip()
            digest = hashlib.sha256(abstract.encode("utf-8")).hexdigest()
            connection.execute(
                """
                INSERT INTO abstracts(
                    paper_id, language, content, content_hash, is_preferred, created_at
                ) VALUES(?, 'en', ?, ?, 1, ?)
                ON CONFLICT(paper_id, source_id, language, content_hash) DO NOTHING
                """,
                (request.paper_id, abstract, digest, utc_now()),
            )
        if request.authors is not None:
            connection.execute("DELETE FROM paper_authors WHERE paper_id=?", (request.paper_id,))
            for order, name in enumerate(request.authors):
                cleaned = " ".join(name.split())
                if not cleaned:
                    continue
                normalized = cleaned.casefold()
                connection.execute(
                    """
                    INSERT INTO authors(display_name, normalized_name)
                    VALUES(?, ?) ON CONFLICT DO NOTHING
                    """,
                    (cleaned, normalized),
                )
                author = require_row(
                    connection.execute(
                        "SELECT id FROM authors WHERE normalized_name=? ORDER BY id LIMIT 1",
                        (normalized,),
                    ).fetchone(),
                    "reading PDF author",
                )
                connection.execute(
                    "INSERT INTO paper_authors(paper_id, author_id, author_order) VALUES(?, ?, ?)",
                    (request.paper_id, author[0], order),
                )
        connection.execute(
            "UPDATE pdf_metadata_candidates SET accepted=0 WHERE file_id=?", (file_id,)
        )
        for field_name, value in values.items():
            serialized = "; ".join(value) if isinstance(value, list) else str(value)
            connection.execute(
                """
                INSERT INTO pdf_metadata_candidates(
                    file_id, field_name, candidate_value, page_number, evidence_text,
                    method, confidence, accepted, created_at
                ) VALUES(?, ?, ?, 0, '用户核对并修正', 'manual', 1, 1, ?)
                """,
                (file_id, field_name, serialized, utc_now()),
            )
        refresh_paper_fts(connection, request.paper_id)


def create_app(
    settings: AppSettings,
    *,
    origin: str,
    sessions: SessionManager | None = None,
    lifecycle: LifecycleMonitor | None = None,
    on_shutdown: ShutdownCallback | None = None,
    static_dir: Path | None = None,
    database: DatabaseManager | None = None,
    search_service: SearchService | None = None,
    translation_runtime: TranslationRuntime | None = None,
    child_processes: object | None = None,
    pdf_runtime: PdfRuntime | None = None,
) -> FastAPI:
    settings.paths.ensure()
    session_manager = sessions or SessionManager()
    lifecycle_monitor = lifecycle or LifecycleMonitor(
        heartbeat_timeout_seconds=settings.heartbeat_timeout_seconds,
        idle_shutdown_seconds=settings.idle_shutdown_seconds,
        startup_grace_seconds=settings.startup_grace_seconds,
    )
    shutdown_callback = on_shutdown or (lambda: None)

    local_translation = translation_runtime or (
        TranslationRuntime(
            database=database,
            paths=settings.paths,
            process_owner=child_processes,  # type: ignore[arg-type]
        )
        if database is not None
        else None
    )
    local_pdf = pdf_runtime or (
        PdfRuntime(
            database,
            settings.paths,
            process_owner=child_processes,  # type: ignore[arg-type]
        )
        if database is not None
        else None
    )
    avatar_store = AvatarStore(settings.paths)
    resolved_search_service = search_service or (
        build_search_service(database) if database is not None else None
    )
    local_updates = (
        UpdateService(database.require_core(), resolved_search_service)
        if database is not None and resolved_search_service is not None
        else None
    )

    async def run_update_scheduler() -> None:
        # Give the UI time to open before the first network check. The task exists
        # only inside this FastAPI process and is cancelled during app shutdown.
        await asyncio.sleep(5)
        while True:
            if local_updates is not None:
                await asyncio.to_thread(local_updates.run_due)
            await asyncio.sleep(300)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(
            lifecycle_monitor.run(
                shutdown_callback,
                interval_seconds=settings.monitor_interval_seconds,
            )
        )
        update_task = asyncio.create_task(run_update_scheduler())
        try:
            yield
        finally:
            update_task.cancel()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await update_task
            with suppress(asyncio.CancelledError):
                await task
            if local_translation is not None:
                local_translation.close()
            if local_pdf is not None:
                local_pdf.close()

    app = FastAPI(title="文献管理器", version=__version__, lifespan=lifespan)
    app.add_middleware(
        LocalSessionMiddleware,
        sessions=session_manager,
        origin=origin,
    )
    app.state.sessions = session_manager
    app.state.lifecycle = lifecycle_monitor
    app.state.settings = settings
    app.state.database = database
    app.state.search_service = resolved_search_service
    app.state.updates = local_updates
    app.state.translation = local_translation
    app.state.pdf = local_pdf

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "mode": "local-single-user",
            "database": "ready" if database is not None else "not-initialized",
            "storage": str(settings.paths.root),
            "lifecycle": asdict(lifecycle_monitor.status()),
        }

    @app.get("/launch")
    def launch(token: str = Query(min_length=32)) -> Response:
        if not session_manager.redeem_launch_token(token):
            raise HTTPException(status_code=401, detail="Launch token is invalid or already used")
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            session_manager.session_token,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return response

    @app.get("/api/session")
    def session_status() -> dict[str, bool]:
        return {"authenticated": True}

    @app.post("/api/lifecycle/heartbeat")
    def heartbeat(message: TabMessage) -> dict[str, object]:
        return asdict(lifecycle_monitor.heartbeat(message.tab_id))

    @app.post("/api/lifecycle/goodbye")
    def goodbye(message: TabMessage) -> dict[str, object]:
        return asdict(lifecycle_monitor.goodbye(message.tab_id))

    @app.post("/api/search")
    def search(request: SearchRequest) -> dict[str, object]:
        service: SearchService | None = app.state.search_service
        if service is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        try:
            variants: tuple[str, ...] = (request.text,)
            if request.field in {"topic", "title"} and database is not None:
                variants = PreferenceService(database.require_core()).bilingual_variants(
                    request.text
                )
            queries = tuple(
                SearchQuery(
                    text=text,
                    field=request.field,
                    page=request.page,
                    page_size=request.page_size,
                    cursor=request.cursor,
                    year_from=request.year_from,
                    year_to=request.year_to,
                    sort=request.sort,
                )
                for text in variants
            )
            result = service.search_variants(
                queries,
                refresh=request.refresh,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {**asdict(result), "recognized_queries": list(variants)}

    @app.get("/api/settings")
    def get_settings() -> dict[str, object]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        core = database.require_core()
        values = SettingsRepository(core)
        secrets = SecretStore(core)
        return {
            "wos_api_key": secrets.masked("wos_api_key"),
            "openalex_api_key": secrets.masked("openalex_api_key"),
            "crossref_email": values.get("crossref_email"),
            "personalization_enabled": values.get("personalization_enabled", True),
            "automatic_search_daily_limit": values.get(
                "automatic_search_daily_limit", 10
            ),
            "onboarding_complete": values.get("onboarding_complete", False),
            "avatar_url": avatar_store.url(),
            "display_name": values.get("display_name", "研究者"),
            "storage": str(database.paths.root),
            "cache_limit_mb": 500,
        }

    @app.put("/api/settings")
    def update_settings(request: SettingsUpdate) -> dict[str, object]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        core = database.require_core()
        values = SettingsRepository(core)
        secrets = SecretStore(core)
        if request.wos_api_key:
            secrets.save("wos_api_key", request.wos_api_key)
        if request.openalex_api_key:
            secrets.save("openalex_api_key", request.openalex_api_key)
        if request.crossref_email is not None:
            values.set("crossref_email", request.crossref_email.strip() or None)
        if request.personalization_enabled is not None:
            values.set("personalization_enabled", request.personalization_enabled)
        if request.automatic_search_daily_limit is not None:
            values.set(
                "automatic_search_daily_limit", request.automatic_search_daily_limit
            )
        if request.onboarding_complete is not None:
            values.set("onboarding_complete", request.onboarding_complete)
        if request.display_name is not None:
            display_name = " ".join(request.display_name.split())
            if not display_name:
                raise HTTPException(status_code=422, detail="显示名称不能为空")
            values.set("display_name", display_name)
        app.state.search_service = build_search_service(database)
        if local_updates is not None:
            local_updates.search_service = app.state.search_service
        return get_settings()

    @app.get("/api/profile/avatar")
    def get_avatar() -> FileResponse:
        avatar = avatar_store.current()
        if avatar is None:
            raise HTTPException(status_code=404, detail="尚未设置个人头像")
        return FileResponse(avatar.path, media_type=avatar.media_type)

    @app.post("/api/profile/avatar")
    async def upload_avatar(
        file: Annotated[UploadFile, File(description="PNG、JPEG 或 WebP 头像")],
    ) -> dict[str, str]:
        try:
            content = await file.read(MAX_AVATAR_BYTES + 1)
            avatar_store.save(content)
        except AvatarError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            await file.close()
        avatar_url = avatar_store.url()
        if avatar_url is None:
            raise HTTPException(status_code=500, detail="头像保存失败")
        return {"avatar_url": avatar_url}

    def preferences() -> PreferenceService:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        return PreferenceService(database.require_core())

    def updates() -> UpdateService:
        service: UpdateService | None = app.state.updates
        if service is None:
            raise HTTPException(status_code=503, detail="Update service is not ready")
        return service

    @app.get("/api/preferences/topics")
    def list_research_topics() -> list[dict[str, object]]:
        return preferences().list_topics()

    @app.post("/api/preferences/topics")
    def create_research_topic(request: ResearchTopicRequest) -> dict[str, int]:
        try:
            return {
                "id": preferences().save_topic(
                    request.name, request.query_text, enabled=request.enabled
                )
            }
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.put("/api/preferences/topics/{topic_id}")
    def update_research_topic(
        topic_id: int, request: ResearchTopicRequest
    ) -> dict[str, int]:
        try:
            return {
                "id": preferences().save_topic(
                    request.name,
                    request.query_text,
                    enabled=request.enabled,
                    topic_id=topic_id,
                )
            }
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.delete("/api/preferences/topics/{topic_id}")
    def delete_research_topic(topic_id: int) -> dict[str, bool]:
        preferences().delete_topic(topic_id)
        return {"deleted": True}

    @app.get("/api/preferences/interest-terms")
    def list_interest_terms() -> list[dict[str, object]]:
        return preferences().list_interest_terms()

    @app.post("/api/preferences/interest-terms")
    def create_interest_term(request: InterestTermRequest) -> dict[str, int]:
        try:
            term_id = preferences().add_interest_term(
                request.term,
                request.term_type,
                mapped_term=request.mapped_term,
            )
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"id": term_id}

    @app.delete("/api/preferences/interest-terms/{term_id}")
    def delete_interest_term(term_id: int) -> dict[str, bool]:
        preferences().delete_interest_term(term_id)
        return {"deleted": True}

    @app.get("/api/recommendations")
    def recommendations(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        return serialize_recommendations(
            RecommendationService(database.require_core()).recommend(limit=limit)
        )

    @app.get("/api/journals/subscriptions")
    def list_journal_subscriptions() -> list[dict[str, object]]:
        return updates().list_journals()

    @app.post("/api/journals/subscriptions")
    def create_journal_subscription(request: JournalSubscriptionRequest) -> dict[str, int]:
        try:
            return {"id": updates().follow_journal(request.title, issn_l=request.issn_l)}
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.put("/api/journals/subscriptions/{subscription_id}")
    def update_journal_subscription(
        subscription_id: int, request: EnabledRequest
    ) -> dict[str, bool]:
        try:
            updates().set_journal_enabled(subscription_id, request.enabled)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"updated": True}

    @app.post("/api/journals/subscriptions/{subscription_id}/run")
    def run_journal_subscription(subscription_id: int) -> dict[str, int]:
        try:
            return {"new_count": updates().run_journal(subscription_id)}
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/api/journals/subscriptions/{subscription_id}/papers")
    def list_journal_papers(
        subscription_id: int,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, object]]:
        try:
            return updates().list_journal_papers(subscription_id, limit=limit)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/saved-searches")
    def list_saved_searches() -> list[dict[str, object]]:
        return updates().list_saved_searches()

    @app.post("/api/saved-searches")
    def create_saved_search(request: SavedSearchRequest) -> dict[str, int]:
        try:
            query = SearchQuery(
                text=request.text,
                field=request.field,
                year_from=request.year_from,
                year_to=request.year_to,
                sort=request.sort,
            )
            return {"id": updates().save_search(request.name, query)}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.put("/api/saved-searches/{saved_search_id}")
    def update_saved_search(
        saved_search_id: int, request: EnabledRequest
    ) -> dict[str, bool]:
        try:
            updates().set_saved_search_enabled(saved_search_id, request.enabled)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"updated": True}

    @app.delete("/api/saved-searches/{saved_search_id}")
    def delete_saved_search(saved_search_id: int) -> dict[str, bool]:
        updates().delete_saved_search(saved_search_id)
        return {"deleted": True}

    @app.post("/api/saved-searches/{saved_search_id}/run")
    def run_saved_search(saved_search_id: int) -> dict[str, int]:
        try:
            return {"new_count": updates().run_saved_search(saved_search_id)}
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/api/alerts")
    def list_alerts(unread_only: bool = False) -> list[dict[str, object]]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        return AlertService(database.require_core()).list(unread_only=unread_only)

    @app.post("/api/alerts/read")
    def mark_all_alerts_read() -> dict[str, bool]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        AlertService(database.require_core()).mark_read()
        return {"updated": True}

    @app.post("/api/alerts/{alert_id}/read")
    def mark_alert_read(alert_id: int) -> dict[str, bool]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        AlertService(database.require_core()).mark_read(alert_id)
        return {"updated": True}

    @app.post("/api/papers/save")
    def save_paper(request: SavePaperRequest) -> dict[str, object]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        records = [
            PaperRecord(
                source=source.source,
                source_id=source.source_id,
                title=source.title,
                doi=source.doi,
                wos_uid=source.wos_uid,
                authors=tuple(source.authors),
                journal=source.journal,
                year=source.year,
                abstract=source.abstract,
                url=source.url,
                citations=source.citations,
            )
            for source in request.sources
        ]
        merged = merge_records(records)[0]
        core = database.require_core()
        paper_id = SearchResultRepository(core).save(merged)
        now = utc_now()
        core.execute(
            """
            INSERT INTO user_paper_state(
                paper_id, liked, saved, reading_status, updated_at
            ) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                liked=excluded.liked, saved=excluded.saved,
                reading_status=excluded.reading_status, updated_at=excluded.updated_at
            """,
            (paper_id, int(request.liked), int(request.saved), request.reading_status, now),
        )
        if request.saved:
            library_id = request.library_id
            if library_id is None:
                row = core.execute(
                    """
                    SELECT id FROM libraries WHERE deleted_at IS NULL
                    ORDER BY sort_order, id LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    core.execute(
                        """
                        INSERT INTO libraries(name, created_at, updated_at)
                        VALUES('我的文献', ?, ?)
                        """,
                        (now, now),
                    )
                    library_id = int(core.last_insert_rowid())
                else:
                    library_id = int(row[0])
            core.execute(
                """
                INSERT INTO library_papers(library_id, paper_id, added_at)
                VALUES(?, ?, ?) ON CONFLICT(library_id, paper_id) DO NOTHING
                """,
                (library_id, paper_id, now),
            )
        return {"paper_id": paper_id, "saved": request.saved, "liked": request.liked}

    @app.get("/api/papers/{paper_id}")
    def paper_detail(paper_id: int) -> dict[str, object]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        core = database.require_core()
        row = core.execute(
            """
            SELECT p.id, p.doi, p.wos_uid, p.title_original, p.title_zh,
                   p.journal_title, p.publication_year,
                   coalesce(s.liked, 0), coalesce(s.saved, 0),
                   coalesce(s.reading_status, 'unread')
            FROM papers p LEFT JOIN user_paper_state s ON s.paper_id=p.id
            WHERE p.id=?
            """,
            (paper_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        sources = [
            {
                "source": source,
                "external_id": external_id,
                "url": url,
                "fetched_at": fetched_at,
            }
            for source, external_id, url, fetched_at in core.execute(
                """
                SELECT source, external_id, source_url, fetched_at
                FROM paper_sources WHERE paper_id=? ORDER BY id
                """,
                (paper_id,),
            )
        ]
        abstract_row = core.execute(
            """
            SELECT content FROM abstracts WHERE paper_id=?
            ORDER BY is_preferred DESC, id LIMIT 1
            """,
            (paper_id,),
        ).fetchone()
        translations = [
            {
                "id": int(item[0]),
                "field_name": item[1],
                "translated_text": item[2],
                "model_version": item[3],
                "glossary_version": item[4],
                "created_at": item[5],
            }
            for item in core.execute(
                """
                SELECT id, field_name, translated_text, model_version,
                       glossary_version, created_at
                FROM translations WHERE paper_id=? ORDER BY id DESC
                """,
                (paper_id,),
            )
        ]
        return {
            "id": row[0],
            "doi": row[1],
            "wos_uid": row[2],
            "title": row[3],
            "title_zh": row[4],
            "journal": row[5],
            "year": row[6],
            "liked": bool(row[7]),
            "saved": bool(row[8]),
            "reading_status": row[9],
            "abstract": None if abstract_row is None else abstract_row[0],
            "sources": sources,
            "translations": translations,
        }

    def library_service() -> LibraryService:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        return LibraryService(database.require_core(), database.paths)

    @app.get("/api/libraries")
    def list_libraries(include_deleted: bool = False) -> list[dict[str, object]]:
        return [
            asdict(item)
            for item in library_service().list_libraries(include_deleted=include_deleted)
        ]

    @app.post("/api/libraries")
    def create_library(request: LibraryCreateRequest) -> dict[str, int]:
        try:
            return {"id": library_service().create_library(request.name)}
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/libraries/{library_id}/papers")
    def add_paper_to_library(
        library_id: int, request: LibraryPaperAddRequest
    ) -> dict[str, bool]:
        try:
            added = library_service().add_paper(library_id, request.paper_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"added": added}

    @app.put("/api/libraries/{library_id}")
    def rename_library(library_id: int, request: LibraryCreateRequest) -> dict[str, bool]:
        try:
            library_service().rename_library(library_id, request.name)
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"updated": True}

    @app.delete("/api/libraries/{library_id}")
    def delete_library(library_id: int) -> dict[str, bool]:
        library_service().move_to_trash(library_id)
        return {"deleted": True}

    @app.post("/api/libraries/{library_id}/restore")
    def restore_library(library_id: int) -> dict[str, bool]:
        try:
            library_service().restore_library(library_id)
        except apsw.ConstraintError as error:
            raise HTTPException(
                status_code=409, detail="An active library already uses this name"
            ) from error
        return {"restored": True}

    @app.get("/api/library/papers")
    def list_library_papers(
        library_id: int | None = None,
        q: str | None = Query(default=None, max_length=500),
    ) -> list[dict[str, object]]:
        try:
            return library_service().list_papers(library_id, q)
        except apsw.SQLError as error:
            raise HTTPException(
                status_code=422, detail="The local search query is invalid"
            ) from error

    @app.put("/api/papers/{paper_id}/state")
    def update_paper_state(paper_id: int, request: PaperStateRequest) -> dict[str, bool]:
        library_service().set_state(
            paper_id,
            liked=request.liked,
            disliked=request.disliked,
            saved=request.saved,
            reading_status=request.reading_status,
        )
        return {"updated": True}

    @app.post("/api/tags")
    def tag_papers(request: TagRequest) -> dict[str, int]:
        service = library_service()
        tag_id = service.create_tag(request.name)
        service.tag_papers(tag_id, request.paper_ids, request.library_id)
        return {"tag_id": tag_id}

    @app.post("/api/notes")
    def save_note(request: NoteSaveRequest) -> dict[str, int]:
        note_id, version = library_service().save_note(
            request.paper_id,
            request.body,
            note_id=request.note_id,
            library_id=request.library_id,
        )
        return {"note_id": note_id, "version": version}

    @app.post("/api/notes/append")
    def append_note(request: NoteAppendRequest) -> dict[str, int]:
        note_id, version = library_service().append_note(
            request.paper_id, request.body, library_id=request.library_id
        )
        return {"note_id": note_id, "version": version}

    @app.get("/api/libraries/{library_id}/workspace")
    def get_library_workspace(library_id: int) -> dict[str, object]:
        try:
            return library_service().get_workspace(library_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/library/workspace")
    def get_all_papers_workspace() -> dict[str, object]:
        return library_service().get_workspace(None)

    @app.put("/api/libraries/{library_id}/workspace")
    def save_library_workspace(
        library_id: int, request: LibraryWorkspaceRequest
    ) -> dict[str, int]:
        try:
            version = library_service().save_workspace(
                library_id,
                body=request.body,
                note_x=request.note_x,
                note_y=request.note_y,
                note_width=request.note_width,
                note_height=request.note_height,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"version": version}

    @app.put("/api/library/workspace")
    def save_all_papers_workspace(request: LibraryWorkspaceRequest) -> dict[str, int]:
        version = library_service().save_workspace(
            None,
            body=request.body,
            note_x=request.note_x,
            note_y=request.note_y,
            note_width=request.note_width,
            note_height=request.note_height,
        )
        return {"version": version}

    @app.post("/api/libraries/{library_id}/workspace/cards")
    def add_library_workspace_card(
        library_id: int, request: LibraryWorkspaceCardCreate
    ) -> dict[str, int]:
        try:
            return {"id": library_service().add_workspace_card(library_id, request.paper_id)}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/library/workspace/cards")
    def add_all_papers_workspace_card(
        request: LibraryWorkspaceCardCreate,
    ) -> dict[str, int]:
        try:
            return {"id": library_service().add_workspace_card(None, request.paper_id)}
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.put("/api/library-workspace/cards/{card_id}")
    def update_library_workspace_card(
        card_id: int, request: LibraryWorkspaceCardUpdate
    ) -> dict[str, bool]:
        try:
            library_service().update_workspace_card(
                card_id,
                x=request.x,
                y=request.y,
                width=request.width,
                height=request.height,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"updated": True}

    @app.delete("/api/library-workspace/cards/{card_id}")
    def delete_library_workspace_card(card_id: int) -> dict[str, bool]:
        try:
            library_service().delete_workspace_card(card_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"deleted": True}

    @app.post("/api/library/export")
    def export_papers(request: ExportRequest) -> Response:
        filename, content = library_service().export(request.paper_ids, request.format)
        media_types = {
            "bibtex": "application/x-bibtex",
            "ris": "application/x-research-info-systems",
            "csv": "text/csv",
        }
        return Response(
            content,
            media_type=media_types[request.format],
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/storage/stats")
    def storage_stats() -> dict[str, int]:
        return library_service().storage_usage()

    def translation() -> TranslationRuntime:
        runtime: TranslationRuntime | None = app.state.translation
        if runtime is None:
            raise HTTPException(status_code=503, detail="本地翻译服务尚未初始化")
        return runtime

    @app.get("/api/translation/model")
    def translation_model_status() -> dict[str, object]:
        return translation().model_status()

    @app.post("/api/translation/model/download")
    def download_translation_model(request: ModelDownloadRequest) -> dict[str, int]:
        try:
            return {"job_id": translation().submit_download(confirmed=request.confirmed)}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/translation/jobs")
    def create_translation_job(request: TranslationRequest) -> dict[str, int]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        exists = database.require_core().execute(
            "SELECT 1 FROM papers WHERE id=?", (request.paper_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        job_id = translation().coordinator.submit(
            paper_id=request.paper_id,
            field_name=request.field_name,
            save=request.save,
            use_glossary=request.use_glossary,
        )
        return {"job_id": job_id}

    @app.post("/api/translation/text-jobs")
    def create_text_translation_job(request: TextTranslationRequest) -> dict[str, int]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        exists = database.require_core().execute(
            "SELECT 1 FROM papers WHERE id=?", (request.paper_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        job_id = translation().coordinator.submit_text(
            paper_id=request.paper_id,
            source_text=request.text.strip(),
            use_glossary=request.use_glossary,
        )
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: int) -> dict[str, object]:
        payload = translation().job_payload(job_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return payload

    @app.post("/api/translation/jobs/{job_id}/cancel")
    def cancel_translation(job_id: int) -> dict[str, bool]:
        return {"cancelled": translation().coordinator.cancel(job_id)}

    @app.get("/api/translation/glossary")
    def list_glossary() -> list[dict[str, object]]:
        return translation().glossary.list_user_terms()

    @app.post("/api/translation/glossary")
    def add_glossary_term(request: GlossaryTermRequest) -> dict[str, int]:
        try:
            term_id = translation().glossary.add(
                request.term, request.mapped_term, request.term_type
            )
        except (ValueError, apsw.ConstraintError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"id": term_id}

    @app.delete("/api/translation/glossary/{term_id}")
    def delete_glossary_term(term_id: int) -> dict[str, bool]:
        translation().glossary.delete(term_id)
        return {"deleted": True}

    def pdfs() -> PdfRuntime:
        runtime: PdfRuntime | None = app.state.pdf
        if runtime is None:
            raise HTTPException(status_code=503, detail="PDF service is not initialized")
        return runtime

    def pdf_reader() -> PdfReaderService:
        return PdfReaderService(
            library_service().connection,
            library_service(),
        )

    @app.post("/api/pdfs/preview")
    async def preview_pdf(
        file: Annotated[UploadFile, File()],
        paper_id: int | None = Query(default=None, gt=0),
    ) -> dict[str, object]:
        token = new_upload_token()
        target = pdfs().ingest.temporary_path(token)
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open("xb") as destination:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_PDF_BYTES:
                        raise HTTPException(status_code=413, detail="PDF exceeds 250 MB")
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if size == 0:
                raise PdfUploadError("上传的 PDF 是空文件")
            staged = pdfs().ingest.preview_staged(
                token=token,
                filename=file.filename or "document.pdf",
                sha256=digest.hexdigest(),
                size_bytes=size,
                paper_id=paper_id,
            )
        except HTTPException:
            target.unlink(missing_ok=True)
            raise
        except (PdfUploadError, PdfAnalysisError, OSError) as error:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(error)) from error
        return asdict(staged)

    @app.post("/api/pdfs/confirm")
    def confirm_pdf(request: PdfConfirmRequest) -> dict[str, object]:
        if request.resolution == "cancel":
            pdfs().ingest.cancel(request.upload_token)
            return {"cancelled": True}
        try:
            paper_id, file_id, path, deduplicated = pdfs().ingest.confirm(
                token=request.upload_token,
                paper_id=request.paper_id,
                resolution=request.resolution,
                matched_paper_id=request.matched_paper_id,
            )
        except (PdfUploadError, PdfAnalysisError, StorageError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        job_id = pdfs().processing.submit(file_id, path)
        return {
            "paper_id": paper_id,
            "file_id": file_id,
            "job_id": job_id,
            "deduplicated": deduplicated,
        }

    @app.post("/api/pdfs/jobs/{job_id}/cancel")
    def cancel_pdf_processing(job_id: int) -> dict[str, bool]:
        return {"cancelled": pdfs().processing.cancel(job_id)}

    @app.get("/api/pdfs/{file_id}/analysis")
    def pdf_analysis(file_id: int) -> dict[str, object]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        core = database.require_core()
        file_row = core.execute(
            "SELECT id, original_name, sha256, page_count FROM files WHERE id=?", (file_id,)
        ).fetchone()
        if file_row is None:
            raise HTTPException(status_code=404, detail="PDF not found")
        pages = [
            {
                "page_number": row[0],
                "classification": row[1],
                "source": row[2],
                "confidence": row[3],
            }
            for row in core.execute(
                """
                SELECT page_number, classification, text_source, confidence
                FROM pdf_pages WHERE file_id=? ORDER BY page_number
                """,
                (file_id,),
            )
        ]
        candidates = [
            {
                "id": row[0],
                "field_name": row[1],
                "value": row[2],
                "page_number": row[3],
                "evidence": row[4],
                "method": row[5],
                "confidence": row[6],
                "accepted": bool(row[7]),
            }
            for row in core.execute(
                """
                SELECT id, field_name, candidate_value, page_number, evidence_text,
                       method, confidence, accepted
                FROM pdf_metadata_candidates WHERE file_id=?
                ORDER BY field_name, confidence DESC, id
                """,
                (file_id,),
            )
        ]
        return {
            "file_id": file_row[0],
            "name": file_row[1],
            "sha256": file_row[2],
            "page_count": file_row[3],
            "pages": pages,
            "candidates": candidates,
        }

    @app.put("/api/pdfs/{file_id}/metadata")
    def apply_pdf_metadata(file_id: int, request: PdfMetadataUpdate) -> dict[str, bool]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        core = database.require_core()
        linked = core.execute(
            "SELECT 1 FROM paper_files WHERE file_id=? AND paper_id=?",
            (file_id, request.paper_id),
        ).fetchone()
        if linked is None:
            raise HTTPException(status_code=404, detail="PDF is not linked to this paper")
        _apply_pdf_metadata(core, file_id, request)
        return {"updated": True}

    @app.get("/api/papers/{paper_id}/pdfs")
    def paper_pdfs(paper_id: int) -> list[dict[str, object]]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        return [
            {
                "file_id": int(row[0]),
                "name": row[1],
                "sha256": row[2],
                "size_bytes": int(row[3]),
                "page_count": int(row[4]),
                "version_role": row[5],
                "missing": bool(row[6]),
            }
            for row in database.require_core().execute(
                """
                SELECT f.id, f.original_name, f.sha256, f.size_bytes, f.page_count,
                       pf.version_role, f.is_missing
                FROM files f JOIN paper_files pf ON pf.file_id=f.id
                WHERE pf.paper_id=? ORDER BY
                    CASE pf.version_role WHEN 'primary' THEN 0 ELSE 1 END, pf.created_at DESC
                """,
                (paper_id,),
            )
        ]

    @app.get("/api/pdfs/{file_id}/content")
    def pdf_content(file_id: int) -> Response:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        core = database.require_core()
        row = core.execute(
            "SELECT original_name, sha256, is_missing FROM files WHERE id=?", (file_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="PDF not found")
        if bool(row[2]):
            raise HTTPException(
                status_code=410, detail="PDF file is missing from the local library"
            )
        try:
            path = pdfs().ingest.path_for_file(file_id)
        except StorageError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if not path.is_file():
            raise HTTPException(
                status_code=410, detail="PDF file is missing from the local library"
            )
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=str(row[0]),
            content_disposition_type="inline",
            headers={
                "ETag": f'"{row[1]}"',
                "Cache-Control": "private, max-age=3600, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/pdfs/{file_id}/pages")
    def pdf_pages(file_id: int) -> list[dict[str, object]]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        return [
            {
                "page_number": int(row[0]),
                "width": row[1],
                "height": row[2],
                "classification": row[3],
                "source": row[4],
                "content": row[5],
                "blocks": json.loads(str(row[6])),
                "confidence": row[7],
            }
            for row in database.require_core().execute(
                """
                SELECT page_number, width, height, classification, text_source,
                       content, blocks_json, confidence
                FROM pdf_pages WHERE file_id=? ORDER BY page_number
                """,
                (file_id,),
            )
        ]

    @app.get("/api/pdfs/{file_id}/position")
    def get_pdf_position(file_id: int, paper_id: int = Query(gt=0)) -> dict[str, object]:
        try:
            return asdict(pdf_reader().get_position(file_id, paper_id))
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.put("/api/pdfs/{file_id}/position")
    def save_pdf_position(
        file_id: int, request: PdfReadingPositionRequest
    ) -> dict[str, bool]:
        try:
            pdf_reader().save_position(
                file_id,
                request.paper_id,
                request.page_number,
                request.scale,
                request.scroll_offset,
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"updated": True}

    @app.get("/api/pdfs/{file_id}/annotations")
    def list_pdf_annotations(
        file_id: int,
        paper_id: int = Query(gt=0),
        annotation_type: str | None = Query(default=None),
        q: str | None = Query(default=None, max_length=500),
    ) -> list[dict[str, object]]:
        try:
            return pdf_reader().list_annotations(
                file_id, paper_id, annotation_type=annotation_type, query=q
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/pdfs/{file_id}/annotations")
    def create_pdf_annotation(
        file_id: int, request: PdfAnnotationRequest
    ) -> dict[str, int]:
        try:
            annotation_id = pdf_reader().create_annotation(
                file_id,
                request.paper_id,
                annotation_type=request.annotation_type,
                page_number=request.page_number,
                color=request.color,
                selected_text=request.selected_text,
                prefix_text=request.prefix_text,
                suffix_text=request.suffix_text,
                rects=[rect.model_dump() for rect in request.rects],
                comment_text=request.comment_text,
            )
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"id": annotation_id}

    @app.put("/api/pdf-annotations/{annotation_id}")
    def update_pdf_annotation(
        annotation_id: int, request: PdfAnnotationUpdate
    ) -> dict[str, bool]:
        try:
            pdf_reader().update_annotation(
                annotation_id, color=request.color, comment_text=request.comment_text
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"updated": True}

    @app.delete("/api/pdf-annotations/{annotation_id}")
    def delete_pdf_annotation(annotation_id: int) -> dict[str, bool]:
        pdf_reader().delete_annotation(annotation_id)
        return {"deleted": True}

    async def read_import(file: UploadFile) -> tuple[str, bytes]:
        data = await file.read(MAX_IMPORT_BYTES + 1)
        if len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="Import file exceeds 25 MB")
        return file.filename or "wos-export", data

    @app.post("/api/import/wos/preview")
    async def preview_wos_import(file: Annotated[UploadFile, File()]) -> dict[str, object]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        filename, data = await read_import(file)
        try:
            preview = WosImportService(database.require_core()).preview(filename, data)
        except ImportValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return asdict(preview)

    @app.post("/api/import/wos/confirm")
    async def confirm_wos_import(file: Annotated[UploadFile, File()]) -> dict[str, object]:
        if database is None:
            raise HTTPException(status_code=503, detail="Local database is not ready")
        filename, data = await read_import(file)
        try:
            report = WosImportService(database.require_core()).import_file(filename, data)
        except ImportValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return asdict(report)

    resolved_static = static_dir.resolve() if static_dir and static_dir.exists() else None
    if resolved_static:
        assets = resolved_static / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}")
        def frontend(request: Request, path: str) -> Response:
            requested = (resolved_static / path).resolve()
            if requested.is_relative_to(resolved_static) and requested.is_file():
                return FileResponse(requested)
            return FileResponse(resolved_static / "index.html")
    else:

        @app.get("/")
        def development_root() -> dict[str, str]:
            return {"app": "文献管理器", "frontend": "not built"}

    return app
