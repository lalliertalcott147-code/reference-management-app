from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import apsw

from .search.models import SearchQuery
from .search.persistence import SearchResultRepository
from .search.service import CombinedSearchResult, SearchService
from .storage.database import require_row, transaction, utc_now
from .storage.repositories import SettingsRepository, normalize_title

DEFAULT_AUTOMATIC_DAILY_LIMIT = 10
MAX_AUTOMATIC_DAILY_LIMIT = 50
CHECK_INTERVAL = timedelta(days=1)


def _clean(value: str, *, max_length: int) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("内容不能为空")
    if len(cleaned) > max_length:
        raise ValueError(f"内容不能超过 {max_length} 个字符")
    return cleaned


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)


def _next_check(now: datetime) -> str:
    return (now + CHECK_INTERVAL).isoformat()


def _fingerprint(identities: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(identities)).encode("utf-8")).hexdigest()


def _query_from_json(value: str) -> SearchQuery:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("保存的检索条件无效")
    allowed = {
        "text",
        "field",
        "page",
        "page_size",
        "cursor",
        "year_from",
        "year_to",
        "sort",
    }
    return SearchQuery(**{key: item for key, item in payload.items() if key in allowed})


@dataclass(frozen=True)
class Recommendation:
    paper_id: int
    title: str
    journal: str | None
    year: int | None
    score: int
    reasons: tuple[str, ...]


class PreferenceService:
    """Explicit local preferences. This service never reads notes or PDF page text."""

    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    def list_topics(self) -> list[dict[str, object]]:
        return [
            {
                "id": int(row[0]),
                "name": str(row[1]),
                "query_text": str(row[2]),
                "enabled": bool(row[3]),
            }
            for row in self.connection.execute(
                "SELECT id, name, query_text, enabled FROM research_topics ORDER BY id"
            )
        ]

    def save_topic(
        self,
        name: str,
        query_text: str,
        *,
        enabled: bool = True,
        topic_id: int | None = None,
    ) -> int:
        cleaned_name = _clean(name, max_length=120)
        cleaned_query = _clean(query_text, max_length=500)
        now = utc_now()
        if topic_id is None:
            self.connection.execute(
                """
                INSERT INTO research_topics(name, query_text, enabled, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (cleaned_name, cleaned_query, int(enabled), now, now),
            )
            return int(self.connection.last_insert_rowid())
        self.connection.execute(
            """
            UPDATE research_topics SET name=?, query_text=?, enabled=?, updated_at=?
            WHERE id=?
            """,
            (cleaned_name, cleaned_query, int(enabled), now, topic_id),
        )
        if self.connection.changes() == 0:
            raise ValueError("研究主题不存在")
        return topic_id

    def delete_topic(self, topic_id: int) -> None:
        self.connection.execute("DELETE FROM research_topics WHERE id=?", (topic_id,))

    def list_interest_terms(self) -> list[dict[str, object]]:
        return [
            {"id": int(row[0]), "term": str(row[1]), "term_type": str(row[2])}
            for row in self.connection.execute(
                """
                SELECT id, term, term_type FROM interest_terms
                WHERE term_type IN ('positive', 'negative') ORDER BY term_type, term
                """
            )
        ]

    def add_interest_term(self, term: str, term_type: Literal["positive", "negative"]) -> int:
        cleaned = _clean(term, max_length=160)
        self.connection.execute(
            "INSERT INTO interest_terms(term, term_type, created_at) VALUES(?, ?, ?)",
            (cleaned, term_type, utc_now()),
        )
        return int(self.connection.last_insert_rowid())

    def delete_interest_term(self, term_id: int) -> None:
        self.connection.execute(
            "DELETE FROM interest_terms WHERE id=? AND term_type IN ('positive', 'negative')",
            (term_id,),
        )


class RecommendationService:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    @staticmethod
    def _terms(value: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                token.casefold()
                for token in re.findall(r"[\w-]+", value, flags=re.UNICODE)
                if len(token) >= 2
            )
        )

    def recommend(self, *, limit: int = 20) -> list[Recommendation]:
        settings = SettingsRepository(self.connection)
        behavioral = bool(settings.get("personalization_enabled", True))
        topics = [
            (str(row[0]), self._terms(str(row[1])))
            for row in self.connection.execute(
                "SELECT name, query_text FROM research_topics WHERE enabled=1"
            )
        ]
        positive = [
            str(row[0]).casefold()
            for row in self.connection.execute(
                "SELECT term FROM interest_terms WHERE term_type='positive'"
            )
        ]
        negative = [
            str(row[0]).casefold()
            for row in self.connection.execute(
                "SELECT term FROM interest_terms WHERE term_type='negative'"
            )
        ]
        followed = {
            normalize_title(str(row[0])): str(row[0])
            for row in self.connection.execute(
                """
                SELECT j.title FROM journals j JOIN journal_subscriptions s ON s.journal_id=j.id
                WHERE s.enabled=1
                """
            )
        }
        preferred_authors: set[str] = set()
        if behavioral:
            preferred_authors = {
                normalize_title(str(row[0]))
                for row in self.connection.execute(
                    """
                    SELECT DISTINCT a.display_name FROM authors a
                    JOIN paper_authors pa ON pa.author_id=a.id
                    JOIN user_paper_state s ON s.paper_id=pa.paper_id
                    WHERE s.liked=1 OR s.saved=1 OR s.reading_status IN ('reading', 'read')
                    """
                )
            }

        current_year = datetime.now(UTC).year
        recommendations: list[Recommendation] = []
        for row in self.connection.execute(
            """
            SELECT p.id, p.title_original, p.journal_title, p.publication_year,
                   coalesce((SELECT group_concat(content, ' ') FROM abstracts
                             WHERE paper_id=p.id), ''),
                   coalesce(s.disliked, 0)
            FROM papers p LEFT JOIN user_paper_state s ON s.paper_id=p.id
            ORDER BY p.updated_at DESC
            """
        ):
            if bool(row[5]):
                continue
            searchable = f"{row[1]} {row[2] or ''} {row[4]}".casefold()
            reasons: list[str] = []
            score = 0
            for name, terms in topics:
                hits = [term for term in terms if term in searchable]
                if hits:
                    score += 4 + min(len(hits) - 1, 2)
                    reasons.append(f"匹配研究主题“{name}”: {', '.join(hits[:3])}")
            for term in positive:
                if term in searchable:
                    score += 3
                    reasons.append(f"匹配关注关键词“{term}”")
            score -= 4 * sum(term in searchable for term in negative)
            normalized_journal = normalize_title(str(row[2] or ""))
            if normalized_journal in followed:
                score += 3
                reasons.append(f"来自已关注期刊“{followed[normalized_journal]}”")
            if behavioral and preferred_authors:
                authors = [
                    str(author[0])
                    for author in self.connection.execute(
                        """
                        SELECT a.display_name FROM authors a
                        JOIN paper_authors pa ON pa.author_id=a.id
                        WHERE pa.paper_id=? ORDER BY pa.author_order
                        """,
                        (row[0],),
                    )
                ]
                matched = next(
                    (name for name in authors if normalize_title(name) in preferred_authors), None
                )
                if matched:
                    score += 2
                    reasons.append(f"包含你曾保存或阅读的作者: {matched}")
            if row[3] is not None and int(row[3]) >= current_year - 2:
                score += 1
                reasons.append(f"近年发表 ({row[3]})")
            if score > 0 and reasons:
                recommendations.append(
                    Recommendation(
                        int(row[0]), str(row[1]), row[2], row[3], score, tuple(reasons)
                    )
                )
        recommendations.sort(key=lambda item: (-item.score, -(item.year or 0), item.paper_id))
        return recommendations[: max(1, min(limit, 100))]


class AlertService:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    def create(
        self,
        kind: Literal["saved_search", "journal", "quota", "error"],
        title: str,
        message: str,
        *,
        dedupe_key: str,
        related_type: str | None = None,
        related_id: int | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO alerts(
                kind, title, message, related_type, related_id, dedupe_key, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?) ON CONFLICT(dedupe_key) DO NOTHING
            """,
            (kind, title, message, related_type, related_id, dedupe_key, utc_now()),
        )

    def list(self, *, unread_only: bool = False) -> list[dict[str, object]]:
        where = "WHERE is_read=0" if unread_only else ""
        return [
            {
                "id": int(row[0]),
                "kind": str(row[1]),
                "title": str(row[2]),
                "message": str(row[3]),
                "related_type": row[4],
                "related_id": row[5],
                "is_read": bool(row[6]),
                "created_at": str(row[7]),
            }
            for row in self.connection.execute(
                f"""
                SELECT id, kind, title, message, related_type, related_id, is_read, created_at
                FROM alerts {where} ORDER BY created_at DESC, id DESC LIMIT 200
                """
            )
        ]

    def mark_read(self, alert_id: int | None = None) -> None:
        if alert_id is None:
            self.connection.execute("UPDATE alerts SET is_read=1 WHERE is_read=0")
        else:
            self.connection.execute("UPDATE alerts SET is_read=1 WHERE id=?", (alert_id,))


class UpdateService:
    def __init__(self, connection: apsw.Connection, search_service: SearchService) -> None:
        self.connection = connection
        self.search_service = search_service
        self.results = SearchResultRepository(connection)
        self.alerts = AlertService(connection)

    def follow_journal(self, title: str, *, issn_l: str | None = None) -> int:
        cleaned = _clean(title, max_length=300)
        normalized = normalize_title(cleaned)
        now = utc_now()
        with transaction(self.connection):
            row = self.connection.execute(
                "SELECT id FROM journals WHERE normalized_title=? ORDER BY id LIMIT 1",
                (normalized,),
            ).fetchone()
            if row is None:
                self.connection.execute(
                    "INSERT INTO journals(title, issn_l, normalized_title) VALUES(?, ?, ?)",
                    (cleaned, issn_l, normalized),
                )
                journal_id = int(self.connection.last_insert_rowid())
            else:
                journal_id = int(row[0])
            self.connection.execute(
                """
                INSERT INTO journal_subscriptions(journal_id, enabled, next_run_at)
                VALUES(?, 1, ?) ON CONFLICT(journal_id) DO UPDATE SET
                    enabled=1, next_run_at=coalesce(
                        journal_subscriptions.next_run_at, excluded.next_run_at
                    )
                """,
                (journal_id, now),
            )
            subscription = require_row(
                self.connection.execute(
                    "SELECT id FROM journal_subscriptions WHERE journal_id=?", (journal_id,)
                ).fetchone(),
                "reading journal subscription",
            )
        return int(subscription[0])

    def list_journals(self) -> list[dict[str, object]]:
        return [
            {
                "id": int(row[0]),
                "title": str(row[1]),
                "issn_l": row[2],
                "enabled": bool(row[3]),
                "next_run_at": row[4],
                "last_success_at": row[5],
                "last_error": row[6],
                "last_match_count": int(row[7]),
            }
            for row in self.connection.execute(
                """
                SELECT s.id, j.title, j.issn_l, s.enabled, s.next_run_at,
                       s.last_success_at, s.last_error, s.last_match_count
                FROM journal_subscriptions s JOIN journals j ON j.id=s.journal_id
                ORDER BY j.title
                """
            )
        ]

    def set_journal_enabled(self, subscription_id: int, enabled: bool) -> None:
        self.connection.execute(
            "UPDATE journal_subscriptions SET enabled=?, next_run_at=? WHERE id=?",
            (int(enabled), utc_now() if enabled else None, subscription_id),
        )
        if self.connection.changes() == 0:
            raise ValueError("期刊关注不存在")

    def save_search(self, name: str, query: SearchQuery) -> int:
        cleaned = _clean(name, max_length=120)
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO saved_searches(
                name, query_json, enabled, next_run_at, created_at, updated_at
            ) VALUES(?, ?, 1, ?, ?, ?)
            """,
            (cleaned, json.dumps(query.as_dict(), ensure_ascii=False), now, now, now),
        )
        return int(self.connection.last_insert_rowid())

    def list_saved_searches(self) -> list[dict[str, object]]:
        return [
            {
                "id": int(row[0]),
                "name": str(row[1]),
                "query": json.loads(str(row[2])),
                "enabled": bool(row[3]),
                "next_run_at": row[4],
                "last_success_at": row[5],
                "last_error": row[6],
                "last_new_count": int(row[7]),
            }
            for row in self.connection.execute(
                """
                SELECT id, name, query_json, enabled, next_run_at, last_success_at,
                       last_error, last_new_count FROM saved_searches ORDER BY id DESC
                """
            )
        ]

    def set_saved_search_enabled(self, saved_search_id: int, enabled: bool) -> None:
        self.connection.execute(
            "UPDATE saved_searches SET enabled=?, next_run_at=?, updated_at=? WHERE id=?",
            (int(enabled), utc_now() if enabled else None, utc_now(), saved_search_id),
        )
        if self.connection.changes() == 0:
            raise ValueError("保存检索不存在")

    def delete_saved_search(self, saved_search_id: int) -> None:
        self.connection.execute("DELETE FROM saved_searches WHERE id=?", (saved_search_id,))

    def _persist_results(
        self,
        result: CombinedSearchResult,
        *,
        owner_table: Literal["saved_search_items", "journal_subscription_items"],
        owner_column: Literal["saved_search_id", "subscription_id"],
        owner_id: int,
    ) -> tuple[list[str], int]:
        identities: list[str] = []
        new_count = 0
        now = utc_now()
        for paper in result.papers:
            paper_id = self.results.save(paper)
            identities.append(paper.identity)
            existed = self.connection.execute(
                f"SELECT 1 FROM {owner_table} WHERE {owner_column}=? AND result_identity=?",
                (owner_id, paper.identity),
            ).fetchone()
            self.connection.execute(
                f"""
                INSERT INTO {owner_table}(
                    {owner_column}, result_identity, paper_id, first_seen_at, last_seen_at
                ) VALUES(?, ?, ?, ?, ?) ON CONFLICT({owner_column}, result_identity)
                DO UPDATE SET paper_id=excluded.paper_id, last_seen_at=excluded.last_seen_at
                """,
                (owner_id, paper.identity, paper_id, now, now),
            )
            if existed is None:
                new_count += 1
        return identities, new_count

    def _limited(self, result: CombinedSearchResult) -> bool:
        return any(status.state == "limited" for status in result.statuses)

    def run_saved_search(self, saved_search_id: int, *, automatic: bool = False) -> int:
        row = require_row(
            self.connection.execute(
                "SELECT name, query_json FROM saved_searches WHERE id=?", (saved_search_id,)
            ).fetchone(),
            "reading saved search",
        )
        name, query = str(row[0]), _query_from_json(str(row[1]))
        try:
            result = self.search_service.search(query, refresh=True)
            identities, new_count = self._persist_results(
                result,
                owner_table="saved_search_items",
                owner_column="saved_search_id",
                owner_id=saved_search_id,
            )
            now = datetime.now(UTC)
            digest = _fingerprint(identities)
            self.connection.execute(
                """
                UPDATE saved_searches SET last_success_at=?, next_run_at=?,
                    last_result_fingerprint=?, last_error=NULL, last_new_count=?, updated_at=?
                WHERE id=?
                """,
                (
                    now.isoformat(),
                    _next_check(now),
                    digest,
                    new_count,
                    now.isoformat(),
                    saved_search_id,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO saved_search_runs(
                    saved_search_id, result_fingerprint, new_count, status, created_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    saved_search_id,
                    digest,
                    new_count,
                    "limited" if self._limited(result) else "success",
                    now.isoformat(),
                ),
            )
            if new_count:
                self.alerts.create(
                    "saved_search",
                    f"保存检索“{name}”有新结果",
                    f"发现 {new_count} 篇此前未见的文献。",
                    dedupe_key=f"saved_search:{saved_search_id}:{digest}",
                    related_type="saved_search",
                    related_id=saved_search_id,
                )
            if self._limited(result):
                self._quota_alert("外部来源已达到免费额度, 自动检查已暂停到下一周期。")
            return new_count
        except Exception as error:
            self._record_error("saved_searches", saved_search_id, str(error), automatic)
            raise

    def run_journal(self, subscription_id: int, *, automatic: bool = False) -> int:
        row = require_row(
            self.connection.execute(
                """
                SELECT j.title FROM journal_subscriptions s
                JOIN journals j ON j.id=s.journal_id WHERE s.id=?
                """,
                (subscription_id,),
            ).fetchone(),
            "reading journal subscription",
        )
        title = str(row[0])
        try:
            result = self.search_service.search(
                SearchQuery(text=title, field="topic", page_size=50, sort="year_desc"),
                refresh=True,
            )
            matched = tuple(
                paper
                for paper in result.papers
                if normalize_title(paper.journal or "") == normalize_title(title)
            )
            filtered = CombinedSearchResult(matched, result.statuses)
            identities, new_count = self._persist_results(
                filtered,
                owner_table="journal_subscription_items",
                owner_column="subscription_id",
                owner_id=subscription_id,
            )
            now = datetime.now(UTC)
            self.connection.execute(
                """
                UPDATE journal_subscriptions SET last_success_at=?, next_run_at=?,
                    last_error=NULL, last_match_count=? WHERE id=?
                """,
                (now.isoformat(), _next_check(now), len(identities), subscription_id),
            )
            if new_count:
                self.alerts.create(
                    "journal",
                    f"期刊“{title}”有新文献",
                    f"发现 {new_count} 篇此前未见的文献。",
                    dedupe_key=f"journal:{subscription_id}:{_fingerprint(identities)}",
                    related_type="journal",
                    related_id=subscription_id,
                )
            if self._limited(result):
                self._quota_alert("外部来源已达到免费额度, 自动检查已暂停到下一周期。")
            return new_count
        except Exception as error:
            self._record_error("journal_subscriptions", subscription_id, str(error), automatic)
            raise

    def _record_error(self, table: str, item_id: int, message: str, automatic: bool) -> None:
        next_run = _next_check(datetime.now(UTC)) if automatic else None
        self.connection.execute(
            f"UPDATE {table} SET last_error=?, next_run_at=coalesce(?, next_run_at) WHERE id=?",
            (message[:1000], next_run, item_id),
        )
        digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
        self.alerts.create(
            "error",
            "自动更新失败" if automatic else "更新失败",
            message[:500],
            dedupe_key=f"error:{table}:{item_id}:{digest}",
            related_type=table,
            related_id=item_id,
        )

    def _quota_alert(self, message: str) -> None:
        day = datetime.now(UTC).date().isoformat()
        self.alerts.create(
            "quota",
            "免费额度保护已生效",
            message,
            dedupe_key=f"quota:{day}",
        )

    def _automatic_budget_available(self, now: datetime) -> bool:
        values = SettingsRepository(self.connection)
        limit = int(values.get("automatic_search_daily_limit", DEFAULT_AUTOMATIC_DAILY_LIMIT))
        limit = max(1, min(limit, MAX_AUTOMATIC_DAILY_LIMIT))
        day = now.date().isoformat()
        counter = values.get("automatic_search_daily_counter", {"date": day, "count": 0})
        if not isinstance(counter, dict) or counter.get("date") != day:
            counter = {"date": day, "count": 0}
        if int(counter.get("count", 0)) >= limit:
            self._quota_alert(
                f"今日自动检查已达到 {limit} 次上限, 明天打开 App 后可继续。"
            )
            return False
        values.set(
            "automatic_search_daily_counter",
            {"date": day, "count": int(counter.get("count", 0)) + 1},
        )
        return True

    def run_due(self, *, now: datetime | None = None) -> int:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        completed = 0
        due: list[tuple[str, int]] = []
        due.extend(
            ("saved", int(row[0]))
            for row in self.connection.execute(
                """
                SELECT id FROM saved_searches
                WHERE enabled=1 AND (next_run_at IS NULL OR next_run_at<=?) ORDER BY id
                """,
                (current.isoformat(),),
            )
        )
        due.extend(
            ("journal", int(row[0]))
            for row in self.connection.execute(
                """
                SELECT id FROM journal_subscriptions
                WHERE enabled=1 AND (next_run_at IS NULL OR next_run_at<=?) ORDER BY id
                """,
                (current.isoformat(),),
            )
        )
        for kind, item_id in due:
            if not self._automatic_budget_available(current):
                break
            try:
                if kind == "saved":
                    self.run_saved_search(item_id, automatic=True)
                else:
                    self.run_journal(item_id, automatic=True)
            except Exception:
                pass
            completed += 1
        return completed


def serialize_recommendations(items: list[Recommendation]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]
