from __future__ import annotations

from datetime import UTC, datetime

from catalyst_literature.config import AppPaths
from catalyst_literature.storage.database import DatabaseManager, utc_now
from catalyst_literature.storage.repositories import PaperDraft, PaperRepository, SettingsRepository
from catalyst_literature.updates import PreferenceService, RecommendationService, UpdateService


def test_explicit_preferences_and_explainable_recommendations(tmp_path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "data"))
    manager.initialize()
    connection = manager.require_core()
    papers = PaperRepository(connection)
    seed_id = papers.create(PaperDraft("Earlier catalyst work", year=2020))
    candidate_id = papers.create(
        PaperDraft(
            "Photocatalysis for carbon dioxide conversion",
            journal="Catalysis Today",
            year=datetime.now(UTC).year,
        )
    )
    for paper_id in (seed_id, candidate_id):
        connection.execute(
            "INSERT INTO authors(display_name, normalized_name) VALUES('Ada Chen', 'ada chen')"
            if paper_id == seed_id
            else "SELECT 1"
        )
        author_id = int(
            connection.execute(
                "SELECT id FROM authors WHERE normalized_name='ada chen' LIMIT 1"
            ).fetchone()[0]
        )
        connection.execute(
            "INSERT INTO paper_authors(paper_id, author_id, author_order) VALUES(?, ?, 1)",
            (paper_id, author_id),
        )
    connection.execute(
        """
        INSERT INTO user_paper_state(
            paper_id, liked, disliked, saved, reading_status, updated_at
        ) VALUES(?, 1, 0, 1, 'read', ?)
        """,
        (seed_id, utc_now()),
    )

    preferences = PreferenceService(connection)
    topic_id = preferences.save_topic("光催化", "photocatalysis carbon dioxide")
    preferences.add_interest_term("conversion", "positive")
    preferences.add_interest_term("nickel", "negative")
    assert preferences.list_topics()[0]["id"] == topic_id

    subscription_service = UpdateService(connection, object())  # type: ignore[arg-type]
    subscription_service.follow_journal("Catalysis Today")
    result = RecommendationService(connection).recommend()
    candidate = next(item for item in result if item.paper_id == candidate_id)
    assert candidate.score >= 10
    assert any("研究主题" in reason for reason in candidate.reasons)
    assert any("关注期刊" in reason for reason in candidate.reasons)
    assert any("Ada Chen" in reason for reason in candidate.reasons)

    SettingsRepository(connection).set("personalization_enabled", False)
    without_behavior = RecommendationService(connection).recommend()
    candidate = next(item for item in without_behavior if item.paper_id == candidate_id)
    assert not any("Ada Chen" in reason for reason in candidate.reasons)
    manager.close()


def test_disabled_topic_and_disliked_paper_are_not_recommended(tmp_path) -> None:
    manager = DatabaseManager(AppPaths.from_root(tmp_path / "data"))
    manager.initialize()
    connection = manager.require_core()
    paper_id = PaperRepository(connection).create(
        PaperDraft("Electrocatalysis discovery", year=datetime.now(UTC).year)
    )
    PreferenceService(connection).save_topic(
        "电催化", "electrocatalysis", enabled=False
    )
    connection.execute(
        """
        INSERT INTO user_paper_state(
            paper_id, liked, disliked, saved, reading_status, updated_at
        ) VALUES(?, 0, 1, 0, 'unread', ?)
        """,
        (paper_id, utc_now()),
    )
    assert RecommendationService(connection).recommend() == []
    manager.close()
