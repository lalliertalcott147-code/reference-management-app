from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SettingsUpdate(BaseModel):
    wos_api_key: str | None = Field(default=None, max_length=512)
    openalex_api_key: str | None = Field(default=None, max_length=512)
    crossref_email: str | None = Field(default=None, max_length=320)
    personalization_enabled: bool | None = None
    automatic_search_daily_limit: int | None = Field(default=None, ge=1, le=50)
    onboarding_complete: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=80)


class ResearchTopicRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query_text: str = Field(min_length=1, max_length=500)
    enabled: bool = True


class InterestTermRequest(BaseModel):
    term: str = Field(min_length=1, max_length=160)
    mapped_term: str | None = Field(default=None, max_length=160)
    term_type: Literal["positive", "negative"]


class JournalSubscriptionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    issn_l: str | None = Field(default=None, max_length=32)


class EnabledRequest(BaseModel):
    enabled: bool


class SavedSearchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=500)
    field: Literal["topic", "title", "author", "doi"] = "topic"
    year_from: int | None = Field(default=None, ge=1600, le=2200)
    year_to: int | None = Field(default=None, ge=1600, le=2200)
    sort: str = "relevance"


class SourcePayload(BaseModel):
    source: Literal["wos", "openalex", "crossref", "wos_export", "pdf"]
    source_id: str
    title: str
    doi: str | None = None
    wos_uid: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    year: int | None = None
    abstract: str | None = None
    url: str | None = None
    citations: int | None = None


class SavePaperRequest(BaseModel):
    sources: list[SourcePayload] = Field(min_length=1)
    liked: bool = False
    saved: bool = True
    reading_status: Literal["unread", "reading", "read"] = "unread"
    library_id: int | None = None


class LibraryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class LibraryPaperAddRequest(BaseModel):
    paper_id: int = Field(gt=0)


class PaperStateRequest(BaseModel):
    liked: bool = False
    disliked: bool = False
    saved: bool = True
    reading_status: Literal["unread", "reading", "read"] = "unread"


class TagRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    paper_ids: list[int] = Field(min_length=1)
    library_id: int | None = None


class NoteSaveRequest(BaseModel):
    paper_id: int
    body: str = Field(max_length=200_000)
    note_id: int | None = None
    library_id: int | None = None


class NoteAppendRequest(BaseModel):
    paper_id: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=100_000)
    library_id: int | None = Field(default=None, gt=0)


class LibraryWorkspaceRequest(BaseModel):
    body: str = Field(max_length=500_000)
    note_x: float = Field(ge=0, le=50_000)
    note_y: float = Field(ge=0, le=50_000)
    note_width: float = Field(ge=280, le=2_000)
    note_height: float = Field(ge=180, le=2_000)


class LibraryWorkspaceCardCreate(BaseModel):
    paper_id: int = Field(gt=0)


class LibraryWorkspaceCardUpdate(BaseModel):
    x: float = Field(ge=0, le=50_000)
    y: float = Field(ge=0, le=50_000)
    width: float = Field(ge=280, le=2_000)
    height: float = Field(ge=220, le=2_000)


class ExportRequest(BaseModel):
    paper_ids: list[int] = Field(min_length=1)
    format: Literal["bibtex", "ris", "csv"]


class ModelDownloadRequest(BaseModel):
    confirmed: bool


class TranslationRequest(BaseModel):
    paper_id: int = Field(gt=0)
    field_name: Literal["title", "abstract"]
    save: bool = True
    use_glossary: bool = True


class TextTranslationRequest(BaseModel):
    paper_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=20_000)
    use_glossary: bool = True


class GlossaryTermRequest(BaseModel):
    term: str = Field(min_length=1, max_length=160)
    mapped_term: str | None = Field(default=None, max_length=160)
    term_type: Literal["glossary", "do_not_translate"]


class PdfConfirmRequest(BaseModel):
    upload_token: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")
    paper_id: int | None = Field(default=None, gt=0)
    resolution: Literal["attach", "link_existing", "keep_version", "cancel"]
    matched_paper_id: int | None = Field(default=None, gt=0)


class PdfMetadataUpdate(BaseModel):
    paper_id: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=2_000)
    abstract: str | None = Field(default=None, max_length=100_000)
    doi: str | None = Field(default=None, max_length=512)
    authors: list[str] | None = Field(default=None, max_length=200)
    year: int | None = Field(default=None, ge=1600, le=2200)


class PdfReadingPositionRequest(BaseModel):
    paper_id: int = Field(gt=0)
    page_number: int = Field(ge=1)
    scale: float = Field(ge=0.25, le=5)
    scroll_offset: float = Field(default=0, ge=0)


class AnnotationRect(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class PdfAnnotationRequest(BaseModel):
    paper_id: int = Field(gt=0)
    annotation_type: Literal["highlight", "underline", "comment"]
    page_number: int = Field(ge=1)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    selected_text: str = Field(default="", max_length=100_000)
    prefix_text: str = Field(default="", max_length=500)
    suffix_text: str = Field(default="", max_length=500)
    rects: list[AnnotationRect] = Field(min_length=1, max_length=200)
    comment_text: str = Field(default="", max_length=100_000)


class PdfAnnotationUpdate(BaseModel):
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    comment_text: str | None = Field(default=None, max_length=100_000)
