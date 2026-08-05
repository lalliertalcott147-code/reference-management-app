from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from catalyst_literature.search.models import SearchQuery, SourceError
from catalyst_literature.search.query import (
    build_openalex_params,
    build_wos_query,
    query_cache_key,
)
from catalyst_literature.search.sources import (
    CrossrefSource,
    OpenAlexSource,
    WosSource,
    restore_inverted_abstract,
)
from catalyst_literature.search.transport import JsonResponse, RateGate, RetryPolicy

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "api"


class FakeTransport:
    def __init__(self, responses: list[JsonResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Mapping[str, str | int] | None, Mapping[str, str] | None]] = []

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 15,
    ) -> JsonResponse:
        del timeout
        self.calls.append((url, params, headers))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fixture_response(name: str, headers: Mapping[str, str] | None = None) -> JsonResponse:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return JsonResponse(200, payload, headers or {})


def test_query_mapping_is_stable_and_escapes_wos_values() -> None:
    query = SearchQuery('copper "single atom"', year_from=2024, year_to=2026)
    assert build_wos_query(query) == 'TS="copper \\"single atom\\"" AND PY=2024-2026'
    params = build_openalex_params(query, "free-key")
    assert params["search"] == 'copper "single atom"'
    assert params["filter"] == "from_publication_date:2024-01-01,to_publication_date:2026-12-31"
    assert query_cache_key("wos", query) == query_cache_key("wos", query)
    assert query_cache_key("wos", query) != query_cache_key("openalex", query)


def test_wos_contract_parses_metadata_authors_and_quota() -> None:
    transport = FakeTransport(
        [fixture_response("wos_search.json", {"X-RateLimit-Remaining": "49"})]
    )
    page = WosSource("wos-key", transport).search(SearchQuery("photocatalysis"))
    assert page.total == 1
    assert page.quota.remaining == 49
    assert page.records[0].wos_uid == "WOS:000000000000001"
    assert page.records[0].doi == "10.1000/CATALYST.2026"
    assert page.records[0].authors == ("Li, Ming", "Smith, Anna")
    assert transport.calls[0][2] == {"X-ApiKey": "wos-key"}


def test_openalex_contract_restores_abstract_and_usage_headers() -> None:
    transport = FakeTransport(
        [
            fixture_response(
                "openalex_search.json",
                {"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "999"},
            )
        ]
    )
    page = OpenAlexSource("openalex-free", transport).search(
        SearchQuery("10.1000/catalyst.2026", field="doi")
    )
    assert page.records[0].abstract == "Copper catalysts convert carbon dioxide"
    assert page.records[0].authors == ("Ming Li", "Anna Smith")
    assert page.quota.remaining == 999
    assert transport.calls[0][1]["api_key"] == "openalex-free"  # type: ignore[index]


def test_crossref_contract_uses_polite_identity_and_strips_jats() -> None:
    transport = FakeTransport([fixture_response("crossref_search.json")])
    page = CrossrefSource("person@example.edu", transport).search(SearchQuery("copper"))
    record = page.records[0]
    assert record.abstract == "Copper converts CO2 under sunlight."
    assert record.year == 2026
    assert transport.calls[0][1]["mailto"] == "person@example.edu"  # type: ignore[index]
    assert "mailto:person@example.edu" in transport.calls[0][2]["User-Agent"]  # type: ignore[index]


def test_crossref_doi_lookup_does_not_send_list_only_parameters() -> None:
    single = json.loads((FIXTURES / "crossref_search.json").read_text(encoding="utf-8"))
    response = JsonResponse(200, {"message": single["message"]["items"][0]}, {})
    transport = FakeTransport([response])
    page = CrossrefSource(None, transport).search(
        SearchQuery("10.1000/catalyst.2026", field="doi", page_size=1)
    )
    assert len(page.records) == 1
    assert transport.calls[0][1] == {}
    assert transport.calls[0][0].endswith("10.1000%2Fcatalyst.2026")


def test_missing_keys_and_quota_errors_are_explicit() -> None:
    transport = FakeTransport([])
    with pytest.raises(SourceError) as wos_error:
        WosSource(None, transport).search(SearchQuery("x"))
    assert wos_error.value.code == "missing_key"
    limited = FakeTransport([JsonResponse(429, {"message": "limit"}, {})])
    with pytest.raises(SourceError) as openalex_error:
        OpenAlexSource("free", limited).search(SearchQuery("x"))
    assert openalex_error.value.code == "limited"


def test_retry_policy_retries_server_failure_but_not_client_error() -> None:
    delays: list[float] = []
    transport = FakeTransport(
        [JsonResponse(503, {}, {}), JsonResponse(503, {}, {}), JsonResponse(200, {}, {})]
    )
    policy = RetryPolicy(sleeper=delays.append)
    assert policy.get(transport, "https://example.invalid").status_code == 200
    assert delays == [1.0, 2.0]
    client_error = FakeTransport([JsonResponse(401, {}, {})])
    assert policy.get(client_error, "https://example.invalid").status_code == 401
    assert len(client_error.calls) == 1


def test_inverted_abstract_handles_missing_and_sparse_positions() -> None:
    assert restore_inverted_abstract(None) is None
    assert restore_inverted_abstract({"second": [2], "first": [0]}) == "first second"


def test_rate_gate_waits_only_for_the_remaining_interval() -> None:
    clock = [0.0]
    delays: list[float] = []

    def sleep(delay: float) -> None:
        delays.append(delay)
        clock[0] += delay

    gate = RateGate(2, clock=lambda: clock[0], sleeper=sleep)
    gate.wait()
    clock[0] += 0.2
    gate.wait()
    assert delays == pytest.approx([0.3])
