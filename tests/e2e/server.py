from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn
from catalyst_literature.app import create_app
from catalyst_literature.config import AppPaths, AppSettings
from catalyst_literature.search.merge import merge_records
from catalyst_literature.search.models import PaperRecord, SearchQuery, SourceStatus
from catalyst_literature.search.service import CombinedSearchResult
from catalyst_literature.security import SessionManager
from catalyst_literature.storage.database import DatabaseManager
from catalyst_literature.storage.repositories import SettingsRepository

ROOT = Path(__file__).resolve().parents[2]


class FixtureSearch:
    def search(self, _query: SearchQuery, *, refresh: bool = False) -> CombinedSearchResult:
        del refresh
        record = PaperRecord(
            source="wos",
            source_id="WOS:E2E-1",
            wos_uid="WOS:E2E-1",
            title="Visible light photocatalysis for carbon dioxide conversion",
            doi="10.1000/e2e-catalyst",
            authors=("Ada Chen", "Ming Li"),
            journal="Catalysis Today",
            year=2026,
            abstract="A stable public fixture abstract for browser end-to-end testing.",
        )
        return CombinedSearchResult(
            tuple(merge_records([record])),
            (SourceStatus("wos", "success", "fixed E2E response"),),
        )

    def search_variants(
        self,
        queries: tuple[SearchQuery, ...],
        *,
        refresh: bool = False,
    ) -> CombinedSearchResult:
        if not queries:
            raise ValueError("At least one E2E query is required")
        return self.search(queries[0], refresh=refresh)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    arguments = parser.parse_args()
    paths = AppPaths.from_root(arguments.data)
    database = DatabaseManager(paths)
    database.initialize()
    SettingsRepository(database.require_core()).set("onboarding_complete", True)
    sessions = SessionManager()
    origin = f"http://127.0.0.1:{arguments.port}"
    app = create_app(
        AppSettings(paths=paths),
        origin=origin,
        sessions=sessions,
        database=database,
        search_service=FixtureSearch(),  # type: ignore[arg-type]
        static_dir=ROOT / "frontend" / "dist",
    )
    arguments.runtime.write_text(
        json.dumps({"origin": origin, "launch_token": sessions.launch_token}),
        encoding="utf-8",
    )
    try:
        uvicorn.run(app, host="127.0.0.1", port=arguments.port, access_log=False)
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
