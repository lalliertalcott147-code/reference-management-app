from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


CORE_MIGRATIONS = (
    Migration(
        1,
        "core_foundation",
        """
        CREATE TABLE app_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE secrets (
            name TEXT PRIMARY KEY,
            ciphertext TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            doi TEXT UNIQUE,
            wos_uid TEXT UNIQUE,
            title_original TEXT NOT NULL,
            title_zh TEXT,
            normalized_title TEXT NOT NULL,
            weak_fingerprint TEXT,
            journal_title TEXT,
            publication_year INTEGER,
            volume TEXT,
            issue TEXT,
            pages TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX papers_weak_fingerprint_idx ON papers(weak_fingerprint);
        CREATE TABLE paper_sources (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            source_url TEXT,
            raw_summary_json TEXT NOT NULL DEFAULT '{}',
            fetched_at TEXT NOT NULL,
            UNIQUE(source, external_id)
        );
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            orcid TEXT UNIQUE
        );
        CREATE INDEX authors_name_idx ON authors(normalized_name);
        CREATE TABLE paper_authors (
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
            author_order INTEGER NOT NULL,
            PRIMARY KEY(paper_id, author_order),
            UNIQUE(paper_id, author_id)
        );
        CREATE TABLE abstracts (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            source_id INTEGER REFERENCES paper_sources(id) ON DELETE SET NULL,
            language TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            is_preferred INTEGER NOT NULL DEFAULT 0 CHECK(is_preferred IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE(paper_id, source_id, language, content_hash)
        );
        CREATE TABLE translations (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL CHECK(field_name IN ('title', 'abstract')),
            source_hash TEXT NOT NULL,
            target_language TEXT NOT NULL,
            model_version TEXT NOT NULL,
            glossary_version TEXT NOT NULL,
            translated_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(source_hash, target_language, model_version, glossary_version)
        );
        CREATE TABLE user_paper_state (
            paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
            liked INTEGER NOT NULL DEFAULT 0 CHECK(liked IN (0, 1)),
            disliked INTEGER NOT NULL DEFAULT 0 CHECK(disliked IN (0, 1)),
            saved INTEGER NOT NULL DEFAULT 0 CHECK(saved IN (0, 1)),
            reading_status TEXT NOT NULL DEFAULT 'unread'
                CHECK(reading_status IN ('unread', 'reading', 'read')),
            last_viewed_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE libraries (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX libraries_active_name_idx
            ON libraries(lower(name)) WHERE deleted_at IS NULL;
        CREATE TABLE library_papers (
            library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            added_at TEXT NOT NULL,
            PRIMARY KEY(library_id, paper_id)
        );
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
        CREATE TABLE paper_tags (
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            library_id INTEGER REFERENCES libraries(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            UNIQUE(paper_id, tag_id, library_id)
        );
        CREATE TABLE paper_notes (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            library_id INTEGER REFERENCES libraries(id) ON DELETE SET NULL,
            annotation_id INTEGER,
            body TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE files (
            id INTEGER PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256) = 64),
            relative_path TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
            page_count INTEGER NOT NULL DEFAULT 0 CHECK(page_count >= 0),
            mime_type TEXT NOT NULL DEFAULT 'application/pdf',
            is_missing INTEGER NOT NULL DEFAULT 0 CHECK(is_missing IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE paper_files (
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE RESTRICT,
            version_role TEXT NOT NULL DEFAULT 'primary',
            created_at TEXT NOT NULL,
            PRIMARY KEY(paper_id, file_id)
        );
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK(status IN
                ('pending', 'running', 'cancelling', 'cancelled', 'completed', 'failed')),
            progress_current INTEGER NOT NULL DEFAULT 0,
            progress_total INTEGER,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT,
            error_code TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        2,
        "complete_product_schema_and_fts",
        """
        CREATE TABLE research_topics (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            query_text TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE interest_terms (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            mapped_term TEXT,
            term_type TEXT NOT NULL CHECK(term_type IN
                ('positive', 'negative', 'do_not_translate', 'glossary')),
            created_at TEXT NOT NULL,
            UNIQUE(term, term_type)
        );
        CREATE TABLE feedback_events (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER REFERENCES papers(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            personalization_enabled INTEGER NOT NULL CHECK(personalization_enabled IN (0, 1)),
            created_at TEXT NOT NULL
        );
        CREATE TABLE pdf_extractions (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL CHECK(field_name IN ('title', 'abstract', 'doi')),
            extracted_text TEXT NOT NULL,
            user_value TEXT,
            page_number INTEGER NOT NULL,
            boxes_json TEXT NOT NULL DEFAULT '[]',
            method TEXT NOT NULL CHECK(method IN ('text', 'ocr', 'metadata', 'manual')),
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            created_at TEXT NOT NULL
        );
        CREATE TABLE pdf_annotations (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            note_id INTEGER REFERENCES paper_notes(id) ON DELETE SET NULL,
            annotation_type TEXT NOT NULL CHECK(
                annotation_type IN ('highlight', 'underline', 'comment')
            ),
            page_number INTEGER NOT NULL CHECK(page_number >= 1),
            color TEXT NOT NULL,
            selected_text TEXT NOT NULL DEFAULT '',
            prefix_text TEXT NOT NULL DEFAULT '',
            suffix_text TEXT NOT NULL DEFAULT '',
            rects_json TEXT NOT NULL,
            comment_text TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE journals (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            issn_l TEXT UNIQUE,
            issn TEXT,
            normalized_title TEXT NOT NULL
        );
        CREATE TABLE journal_subscriptions (
            id INTEGER PRIMARY KEY,
            journal_id INTEGER NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            next_run_at TEXT,
            last_success_at TEXT,
            last_error TEXT,
            UNIQUE(journal_id)
        );
        CREATE TABLE search_history (
            id INTEGER PRIMARY KEY,
            query_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE saved_searches (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            query_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            next_run_at TEXT,
            last_success_at TEXT,
            last_result_fingerprint TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE saved_search_runs (
            id INTEGER PRIMARY KEY,
            saved_search_id INTEGER NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
            result_fingerprint TEXT NOT NULL,
            new_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE paper_fts USING fts5(
            paper_id UNINDEXED,
            title_original,
            title_zh,
            authors,
            journal,
            abstract_text,
            translation_text,
            tags,
            notes,
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE INDEX jobs_status_idx ON jobs(status, updated_at);
        CREATE INDEX paper_sources_paper_idx ON paper_sources(paper_id);
        CREATE INDEX abstracts_paper_idx ON abstracts(paper_id);
        CREATE INDEX files_missing_idx ON files(is_missing);
        """,
    ),
    Migration(
        3,
        "note_versions",
        """
        CREATE TABLE paper_note_versions (
            id INTEGER PRIMARY KEY,
            note_id INTEGER NOT NULL REFERENCES paper_notes(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            body TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            UNIQUE(note_id, version)
        );
        CREATE UNIQUE INDEX paper_tags_scope_unique
            ON paper_tags(paper_id, tag_id, coalesce(library_id, -1));
        CREATE INDEX paper_notes_paper_idx ON paper_notes(paper_id, updated_at);
        """,
    ),
    Migration(
        4,
        "pdf_pipeline",
        """
        CREATE TABLE pdf_pages (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL CHECK(page_number >= 1),
            width REAL NOT NULL CHECK(width > 0),
            height REAL NOT NULL CHECK(height > 0),
            classification TEXT NOT NULL CHECK(
                classification IN ('text', 'scanned', 'review')
            ),
            text_source TEXT NOT NULL CHECK(text_source IN ('text', 'ocr', 'none')),
            content TEXT NOT NULL DEFAULT '',
            blocks_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            created_at TEXT NOT NULL,
            UNIQUE(file_id, page_number)
        );
        CREATE INDEX pdf_pages_file_idx ON pdf_pages(file_id, page_number);
        CREATE TABLE pdf_metadata_candidates (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL CHECK(
                field_name IN ('title', 'abstract', 'doi', 'authors', 'year')
            ),
            candidate_value TEXT NOT NULL,
            page_number INTEGER NOT NULL CHECK(page_number >= 0),
            evidence_text TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL CHECK(method IN ('text', 'ocr', 'metadata', 'manual')),
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            accepted INTEGER NOT NULL DEFAULT 0 CHECK(accepted IN (0, 1)),
            created_at TEXT NOT NULL
        );
        CREATE INDEX pdf_candidates_file_idx
            ON pdf_metadata_candidates(file_id, field_name, confidence DESC);
        CREATE TABLE pdf_upload_sessions (
            token TEXT PRIMARY KEY,
            temporary_path TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
            size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
            page_count INTEGER NOT NULL CHECK(page_count > 0),
            preview_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        5,
        "pdf_reader_state_and_annotation_integrity",
        """
        CREATE TABLE pdf_reading_positions (
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL DEFAULT 1 CHECK(page_number >= 1),
            scale REAL NOT NULL DEFAULT 1 CHECK(scale >= 0.25 AND scale <= 5),
            scroll_offset REAL NOT NULL DEFAULT 0 CHECK(scroll_offset >= 0),
            updated_at TEXT NOT NULL,
            PRIMARY KEY(file_id, paper_id)
        );
        ALTER TABLE pdf_annotations ADD COLUMN file_sha256 TEXT NOT NULL DEFAULT '';
        ALTER TABLE pdf_annotations ADD COLUMN is_stale INTEGER NOT NULL DEFAULT 0
            CHECK(is_stale IN (0, 1));
        CREATE INDEX pdf_annotations_file_page_idx
            ON pdf_annotations(file_id, page_number, annotation_type);
        """,
    ),
    Migration(
        6,
        "recommendations_subscriptions_and_alerts",
        """
        ALTER TABLE journal_subscriptions ADD COLUMN last_match_count INTEGER NOT NULL
            DEFAULT 0 CHECK(last_match_count >= 0);
        ALTER TABLE saved_searches ADD COLUMN last_new_count INTEGER NOT NULL
            DEFAULT 0 CHECK(last_new_count >= 0);
        CREATE TABLE saved_search_items (
            saved_search_id INTEGER NOT NULL
                REFERENCES saved_searches(id) ON DELETE CASCADE,
            result_identity TEXT NOT NULL,
            paper_id INTEGER REFERENCES papers(id) ON DELETE SET NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY(saved_search_id, result_identity)
        );
        CREATE TABLE journal_subscription_items (
            subscription_id INTEGER NOT NULL
                REFERENCES journal_subscriptions(id) ON DELETE CASCADE,
            result_identity TEXT NOT NULL,
            paper_id INTEGER REFERENCES papers(id) ON DELETE SET NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY(subscription_id, result_identity)
        );
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN
                ('saved_search', 'journal', 'quota', 'error')),
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            related_type TEXT,
            related_id INTEGER,
            dedupe_key TEXT NOT NULL UNIQUE,
            is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0, 1)),
            created_at TEXT NOT NULL
        );
        CREATE INDEX alerts_unread_idx ON alerts(is_read, created_at DESC);
        CREATE INDEX saved_searches_due_idx ON saved_searches(enabled, next_run_at);
        CREATE INDEX journal_subscriptions_due_idx
            ON journal_subscriptions(enabled, next_run_at);
        """,
    ),
)


CACHE_MIGRATIONS = (
    Migration(
        1,
        "cache_foundation",
        """
        CREATE TABLE search_cache (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE metadata_cache (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE paper_candidates (
            candidate_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE translation_cache (
            cache_key TEXT PRIMARY KEY,
            translated_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE recommendation_cache (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE pdf_page_cache (
            cache_key TEXT PRIMARY KEY,
            file_sha256 TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(file_sha256, page_number)
        );
        CREATE TABLE cache_entries (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            cache_key TEXT NOT NULL UNIQUE,
            relative_path TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
            created_at REAL NOT NULL,
            expires_at REAL,
            last_accessed_at REAL NOT NULL
        );
        CREATE INDEX cache_entries_lru_idx ON cache_entries(last_accessed_at, id);
        """,
    ),
)
