from __future__ import annotations

import argparse
import os

from catalyst_literature.search.models import SearchQuery, SourceError
from catalyst_literature.search.service import SearchSource
from catalyst_literature.search.sources import CrossrefSource, OpenAlexSource, WosSource
from catalyst_literature.search.transport import HttpxTransport


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one low-volume live source contract check")
    parser.add_argument("--doi", default="10.1038/s41586-020-2649-2")
    parser.add_argument("--crossref-only", action="store_true")
    args = parser.parse_args()
    transport = HttpxTransport()
    sources: tuple[SearchSource, ...] = (
        CrossrefSource(os.environ.get("CROSSREF_EMAIL"), transport),
    )
    if not args.crossref_only:
        sources += (
            WosSource(os.environ.get("WOS_API_KEY"), transport),
            OpenAlexSource(os.environ.get("OPENALEX_API_KEY"), transport),
        )
    failed = False
    for source in sources:
        try:
            page = source.search(SearchQuery(args.doi, field="doi", page_size=1))
        except SourceError as error:
            print(f"{source.name}: {error.code} - {error}")
            failed = failed or error.code != "missing_key"
        else:
            print(f"{source.name}: ok - {len(page.records)} record(s)")
            failed = failed or not page.records
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
