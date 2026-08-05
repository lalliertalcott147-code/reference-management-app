from __future__ import annotations

from pathlib import Path

from scripts.repository_hygiene import collect_issues

ROOT = Path(__file__).resolve().parents[3]


def test_repository_is_safe_and_documentation_links_resolve() -> None:
    assert collect_issues(ROOT) == []


def test_repository_check_detects_a_broken_relative_link(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("[missing](docs/missing.md)\n", encoding="utf-8")

    issues = collect_issues(tmp_path)

    assert any("broken relative Markdown link" in issue for issue in issues)


def test_repository_check_ignores_local_development_runtime_data(tmp_path: Path) -> None:
    runtime_cache = tmp_path / ".dev-data" / "webview"
    runtime_cache.mkdir(parents=True)
    (runtime_cache / "metadata.json").write_text("{}", encoding="utf-8")

    assert not any(".dev-data" in issue for issue in collect_issues(tmp_path))
