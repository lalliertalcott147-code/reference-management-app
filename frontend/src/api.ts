export interface HealthResponse {
  status: "ok";
  version: string;
  mode: string;
  database: string;
  storage: string;
  lifecycle: {
    active_tabs: number;
    had_tab: boolean;
    empty_for_seconds: number | null;
    shutdown_due: boolean;
  };
}

export interface SettingsResponse {
  wos_api_key: string | null;
  openalex_api_key: string | null;
  crossref_email: string | null;
  personalization_enabled: boolean;
  automatic_search_daily_limit: number;
  onboarding_complete: boolean;
  avatar_url: string | null;
  display_name: string;
  storage: string;
  cache_limit_mb: number;
}

export interface ResearchTopic {
  id: number;
  name: string;
  query_text: string;
  enabled: boolean;
}

export interface InterestTerm {
  id: number;
  term: string;
  term_type: "positive" | "negative";
}

export interface Recommendation {
  paper_id: number;
  title: string;
  journal: string | null;
  year: number | null;
  score: number;
  reasons: string[];
}

export interface JournalSubscription {
  id: number;
  title: string;
  issn_l: string | null;
  enabled: boolean;
  next_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  last_match_count: number;
}

export interface SavedSearch {
  id: number;
  name: string;
  query: {
    text: string;
    field: "topic" | "title" | "author" | "doi";
    year_from?: number | null;
    year_to?: number | null;
    sort?: string;
  };
  enabled: boolean;
  next_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  last_new_count: number;
}

export interface AppAlert {
  id: number;
  kind: "saved_search" | "journal" | "quota" | "error";
  title: string;
  message: string;
  related_type: string | null;
  related_id: number | null;
  is_read: boolean;
  created_at: string;
}

export type SourceName = "wos" | "openalex" | "crossref" | "wos_export" | "pdf";

export interface PaperSource {
  source: SourceName;
  source_id: string;
  title: string;
  doi: string | null;
  wos_uid: string | null;
  authors: string[];
  journal: string | null;
  year: number | null;
  abstract: string | null;
  url: string | null;
  citations: number | null;
}

export interface ProvenanceValue {
  value: unknown;
  source: SourceName;
}

export interface MergedPaper {
  identity: string;
  doi: string | null;
  wos_uid: string | null;
  title: string;
  authors: string[];
  journal: string | null;
  year: number | null;
  abstract: string | null;
  url: string | null;
  citations: number | null;
  sources: PaperSource[];
  provenance: Record<string, ProvenanceValue[]>;
  weak_match: boolean;
}

export interface SourceStatus {
  source: SourceName;
  state: "success" | "cache" | "offline" | "missing_key" | "limited" | "failed";
  message: string;
  fetched_at: string | null;
}

export interface SearchResponse {
  papers: MergedPaper[];
  statuses: SourceStatus[];
}

export interface ImportIssue {
  record_number: number | null;
  field: string | null;
  message: string;
}

export interface ImportPreview {
  format: string;
  total: number;
  new: number;
  duplicates: number;
  missing_doi: number;
  conflicts: number;
  issues: ImportIssue[];
}

export interface ImportReport {
  total: number;
  added: number;
  updated: number;
  skipped: number;
  failed: number;
  issues: ImportIssue[];
}

export interface LibraryRecord {
  id: number;
  name: string;
  sort_order: number;
  deleted_at: string | null;
  paper_count: number;
}

export interface LibraryPaper {
  id: number;
  title: string;
  journal: string | null;
  year: number | null;
  doi: string | null;
  liked: boolean;
  saved: boolean;
  reading_status: "unread" | "reading" | "read";
  has_pdf: boolean;
  file_id: number | null;
  note_id: number | null;
  note: string;
}

export interface WorkspaceCard {
  id: number;
  paper_id: number;
  x: number;
  y: number;
  width: number;
  height: number;
  title: string;
  title_translation: string | null;
  abstract: string;
  abstract_translation: string | null;
  file_id: number | null;
  notes: { id: number; body: string; updated_at: string }[];
}

export interface LibraryWorkspace {
  library_id: number;
  body: string;
  note_x: number;
  note_y: number;
  note_width: number;
  note_height: number;
  version: number;
  updated_at: string;
  cards: WorkspaceCard[];
}

export interface ModelStatus {
  state: "missing" | "invalid" | "ready";
  repository: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  license: string;
  running: boolean;
}

export interface JobStatus {
  id: number;
  kind: string;
  status: "pending" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
  progress_current: number;
  progress_total: number | null;
  result: null | {
    paper_id?: number;
    field_name?: "title" | "abstract" | "selection";
    source_text?: string;
    translated_text?: string;
    saved?: boolean;
  };
  error_code: string | null;
  error_message: string | null;
}

export interface GlossaryTerm {
  id: number;
  term: string;
  mapped_term: string | null;
  term_type: "glossary" | "do_not_translate";
}

export interface PdfCandidate {
  field_name: "title" | "abstract" | "doi" | "authors" | "year";
  value: string;
  page_number: number;
  evidence: string;
  method: "text" | "ocr" | "metadata" | "manual";
  confidence: number;
}

export interface PdfPreview {
  token: string;
  original_name: string;
  sha256: string;
  size_bytes: number;
  page_count: number;
  preview: {
    duplicate_level: "none" | "exact" | "doi" | "weak";
    matches: { paper_id?: number; file_id?: number; title?: string; name?: string }[];
    candidates: PdfCandidate[];
  };
}

export interface PdfFile {
  file_id: number;
  name: string;
  sha256: string;
  size_bytes: number;
  page_count: number;
  version_role: "primary" | "alternate";
  missing: boolean;
}

export interface PdfPageData {
  page_number: number;
  width: number;
  height: number;
  classification: "text" | "scanned" | "review";
  source: "text" | "ocr" | "none";
  content: string;
  blocks: { text: string; rect?: number[]; polygon?: number[][] }[];
  confidence: number;
}

export interface PdfAnnotation {
  id: number;
  note_id: number | null;
  annotation_type: "highlight" | "underline" | "comment";
  page_number: number;
  color: string;
  selected_text: string;
  prefix_text: string;
  suffix_text: string;
  rects: { x: number; y: number; width: number; height: number }[];
  comment_text: string;
  is_stale: boolean;
  updated_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    let message = `本地服务返回 ${response.status}`;
    try {
      const payload = await response.json() as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new Error(message);
  }
  return await response.json() as T;
}

function jsonInit(method: "POST" | "PUT", body: unknown, signal?: AbortSignal): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  };
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request("/api/health", { signal });
}

export function fetchSettings(signal?: AbortSignal): Promise<SettingsResponse> {
  return request("/api/settings", { signal });
}

export function updateSettings(body: Record<string, unknown>): Promise<SettingsResponse> {
  return request("/api/settings", jsonInit("PUT", body));
}

export function uploadProfileAvatar(file: File): Promise<{ avatar_url: string }> {
  return upload("/api/profile/avatar", file);
}

export function fetchResearchTopics(): Promise<ResearchTopic[]> {
  return request("/api/preferences/topics");
}

export function saveResearchTopic(
  body: Omit<ResearchTopic, "id">,
  id?: number,
): Promise<{ id: number }> {
  return request(
    id === undefined ? "/api/preferences/topics" : `/api/preferences/topics/${id}`,
    jsonInit(id === undefined ? "POST" : "PUT", body),
  );
}

export function deleteResearchTopic(id: number): Promise<{ deleted: boolean }> {
  return request(`/api/preferences/topics/${id}`, { method: "DELETE" });
}

export function fetchInterestTerms(): Promise<InterestTerm[]> {
  return request("/api/preferences/interest-terms");
}

export function addInterestTerm(
  term: string,
  termType: InterestTerm["term_type"],
): Promise<{ id: number }> {
  return request("/api/preferences/interest-terms", jsonInit("POST", {
    term,
    term_type: termType,
  }));
}

export function deleteInterestTerm(id: number): Promise<{ deleted: boolean }> {
  return request(`/api/preferences/interest-terms/${id}`, { method: "DELETE" });
}

export function fetchRecommendations(): Promise<Recommendation[]> {
  return request("/api/recommendations");
}

export function fetchAlerts(unreadOnly = false): Promise<AppAlert[]> {
  return request(`/api/alerts?unread_only=${String(unreadOnly)}`);
}

export function markAllAlertsRead(): Promise<{ updated: boolean }> {
  return request("/api/alerts/read", { method: "POST" });
}

export function fetchJournalSubscriptions(): Promise<JournalSubscription[]> {
  return request("/api/journals/subscriptions");
}

export function followJournal(title: string, issnL?: string): Promise<{ id: number }> {
  return request("/api/journals/subscriptions", jsonInit("POST", {
    title,
    issn_l: issnL || null,
  }));
}

export function setJournalEnabled(id: number, enabled: boolean): Promise<{ updated: boolean }> {
  return request(`/api/journals/subscriptions/${id}`, jsonInit("PUT", { enabled }));
}

export function runJournal(id: number): Promise<{ new_count: number }> {
  return request(`/api/journals/subscriptions/${id}/run`, { method: "POST" });
}

export function fetchSavedSearches(): Promise<SavedSearch[]> {
  return request("/api/saved-searches");
}

export function createSavedSearch(body: Record<string, unknown>): Promise<{ id: number }> {
  return request("/api/saved-searches", jsonInit("POST", body));
}

export function setSavedSearchEnabled(id: number, enabled: boolean): Promise<{ updated: boolean }> {
  return request(`/api/saved-searches/${id}`, jsonInit("PUT", { enabled }));
}

export function runSavedSearch(id: number): Promise<{ new_count: number }> {
  return request(`/api/saved-searches/${id}/run`, { method: "POST" });
}

export function deleteSavedSearch(id: number): Promise<{ deleted: boolean }> {
  return request(`/api/saved-searches/${id}`, { method: "DELETE" });
}

export function searchPapers(
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  return request("/api/search", jsonInit("POST", body, signal));
}

export function savePaper(
  paper: MergedPaper,
  options: { liked?: boolean; saved?: boolean; reading_status?: string } = {},
): Promise<{ paper_id: number }> {
  return request("/api/papers/save", jsonInit("POST", {
    sources: paper.sources,
    liked: options.liked ?? false,
    saved: options.saved ?? true,
    reading_status: options.reading_status ?? "unread",
  }));
}

function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  return request(path, { method: "POST", body: form });
}

export function previewWosImport(file: File): Promise<ImportPreview> {
  return upload("/api/import/wos/preview", file);
}

export function confirmWosImport(file: File): Promise<ImportReport> {
  return upload("/api/import/wos/confirm", file);
}

export function fetchLibraries(includeDeleted = false): Promise<LibraryRecord[]> {
  return request(`/api/libraries?include_deleted=${String(includeDeleted)}`);
}

export function createLibrary(name: string): Promise<{ id: number }> {
  return request("/api/libraries", jsonInit("POST", { name }));
}

export function deleteLibrary(id: number): Promise<{ deleted: boolean }> {
  return request(`/api/libraries/${id}`, { method: "DELETE" });
}

export function restoreLibrary(id: number): Promise<{ restored: boolean }> {
  return request(`/api/libraries/${id}/restore`, { method: "POST" });
}

export function fetchLibraryPapers(libraryId?: number, query = ""): Promise<LibraryPaper[]> {
  const parameters = new URLSearchParams();
  if (libraryId !== undefined) parameters.set("library_id", String(libraryId));
  if (query.trim()) parameters.set("q", query.trim());
  return request(`/api/library/papers?${parameters.toString()}`);
}

export function updatePaperState(paper: LibraryPaper): Promise<{ updated: boolean }> {
  return request(`/api/papers/${paper.id}/state`, jsonInit("PUT", {
    liked: paper.liked,
    disliked: false,
    saved: paper.saved,
    reading_status: paper.reading_status,
  }));
}

export function assignTag(name: string, paperIds: number[], libraryId?: number): Promise<{ tag_id: number }> {
  return request("/api/tags", jsonInit("POST", {
    name,
    paper_ids: paperIds,
    library_id: libraryId,
  }));
}

export function saveNote(
  paperId: number,
  body: string,
  noteId: number | null,
  libraryId?: number,
): Promise<{ note_id: number; version: number }> {
  return request("/api/notes", jsonInit("POST", {
    paper_id: paperId,
    body,
    note_id: noteId,
    library_id: libraryId,
  }));
}

export function appendNote(
  paperId: number,
  body: string,
  libraryId?: number,
): Promise<{ note_id: number; version: number }> {
  return request("/api/notes/append", jsonInit("POST", {
    paper_id: paperId,
    body,
    library_id: libraryId,
  }));
}

export function fetchLibraryWorkspace(libraryId: number): Promise<LibraryWorkspace> {
  return request(`/api/libraries/${libraryId}/workspace`);
}

export function saveLibraryWorkspace(
  libraryId: number,
  workspace: Pick<LibraryWorkspace, "body" | "note_x" | "note_y" | "note_width" | "note_height">,
): Promise<{ version: number }> {
  return request(`/api/libraries/${libraryId}/workspace`, jsonInit("PUT", workspace));
}

export function addWorkspaceCard(
  libraryId: number,
  paperId: number,
): Promise<{ id: number }> {
  return request(`/api/libraries/${libraryId}/workspace/cards`, jsonInit("POST", {
    paper_id: paperId,
  }));
}

export function updateWorkspaceCard(
  cardId: number,
  layout: Pick<WorkspaceCard, "x" | "y" | "width" | "height">,
): Promise<{ updated: boolean }> {
  return request(`/api/library-workspace/cards/${cardId}`, jsonInit("PUT", layout));
}

export function deleteWorkspaceCard(cardId: number): Promise<{ deleted: boolean }> {
  return request(`/api/library-workspace/cards/${cardId}`, { method: "DELETE" });
}

export async function exportPapers(paperIds: number[], format: "bibtex" | "ris" | "csv"): Promise<void> {
  const response = await fetch("/api/library/export", {
    credentials: "same-origin",
    ...jsonInit("POST", { paper_ids: paperIds, format }),
  });
  if (!response.ok) throw new Error(`导出失败：${response.status}`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `papers.${format === "bibtex" ? "bib" : format}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function fetchModelStatus(): Promise<ModelStatus> {
  return request("/api/translation/model");
}

export function downloadModel(confirmed: boolean): Promise<{ job_id: number }> {
  return request("/api/translation/model/download", jsonInit("POST", { confirmed }));
}

export function submitTranslation(
  paperId: number,
  fieldName: "title" | "abstract",
  save = true,
  useGlossary = true,
): Promise<{ job_id: number }> {
  return request("/api/translation/jobs", jsonInit("POST", {
    paper_id: paperId,
    field_name: fieldName,
    save,
    use_glossary: useGlossary,
  }));
}

export function submitTextTranslation(
  paperId: number,
  text: string,
  useGlossary = true,
): Promise<{ job_id: number }> {
  return request("/api/translation/text-jobs", jsonInit("POST", {
    paper_id: paperId,
    text,
    use_glossary: useGlossary,
  }));
}

export function fetchJob(jobId: number): Promise<JobStatus> {
  return request(`/api/jobs/${jobId}`);
}

export function cancelTranslation(jobId: number): Promise<{ cancelled: boolean }> {
  return request(`/api/translation/jobs/${jobId}/cancel`, { method: "POST" });
}

export function fetchGlossary(): Promise<GlossaryTerm[]> {
  return request("/api/translation/glossary");
}

export function addGlossaryTerm(
  term: string,
  mappedTerm: string | null,
  termType: GlossaryTerm["term_type"],
): Promise<{ id: number }> {
  return request("/api/translation/glossary", jsonInit("POST", {
    term,
    mapped_term: mappedTerm,
    term_type: termType,
  }));
}

export function deleteGlossaryTerm(termId: number): Promise<{ deleted: boolean }> {
  return request(`/api/translation/glossary/${termId}`, { method: "DELETE" });
}

export function previewPdf(file: File, paperId?: number): Promise<PdfPreview> {
  const query = paperId === undefined ? "" : `?paper_id=${paperId}`;
  return upload(`/api/pdfs/preview${query}`, file);
}

export function confirmPdf(body: {
  upload_token: string;
  paper_id?: number;
  resolution: "attach" | "link_existing" | "keep_version" | "cancel";
  matched_paper_id?: number;
}): Promise<{ paper_id: number; file_id: number; job_id: number; deduplicated: boolean }> {
  return request("/api/pdfs/confirm", jsonInit("POST", body));
}

export function applyPdfMetadata(
  fileId: number,
  body: Record<string, unknown>,
): Promise<{ updated: boolean }> {
  return request(`/api/pdfs/${fileId}/metadata`, jsonInit("PUT", body));
}

export function fetchPaperPdfs(paperId: number): Promise<PdfFile[]> {
  return request(`/api/papers/${paperId}/pdfs`);
}

export function fetchPdfPages(fileId: number): Promise<PdfPageData[]> {
  return request(`/api/pdfs/${fileId}/pages`);
}

export function fetchPdfPosition(fileId: number, paperId: number): Promise<{
  page_number: number; scale: number; scroll_offset: number;
}> {
  return request(`/api/pdfs/${fileId}/position?paper_id=${paperId}`);
}

export function savePdfPosition(
  fileId: number,
  paperId: number,
  pageNumber: number,
  scale: number,
  scrollOffset: number,
): Promise<{ updated: boolean }> {
  return request(`/api/pdfs/${fileId}/position`, jsonInit("PUT", {
    paper_id: paperId, page_number: pageNumber, scale, scroll_offset: scrollOffset,
  }));
}

export function fetchPdfAnnotations(
  fileId: number,
  paperId: number,
  filter = "",
  query = "",
): Promise<PdfAnnotation[]> {
  const parameters = new URLSearchParams({ paper_id: String(paperId) });
  if (filter) parameters.set("annotation_type", filter);
  if (query) parameters.set("q", query);
  return request(`/api/pdfs/${fileId}/annotations?${parameters.toString()}`);
}

export function createPdfAnnotation(
  fileId: number,
  body: Record<string, unknown>,
): Promise<{ id: number }> {
  return request(`/api/pdfs/${fileId}/annotations`, jsonInit("POST", body));
}

export function updatePdfAnnotation(
  annotationId: number,
  body: { color?: string; comment_text?: string },
): Promise<{ updated: boolean }> {
  return request(`/api/pdf-annotations/${annotationId}`, jsonInit("PUT", body));
}

export function deletePdfAnnotation(annotationId: number): Promise<{ deleted: boolean }> {
  return request(`/api/pdf-annotations/${annotationId}`, { method: "DELETE" });
}
