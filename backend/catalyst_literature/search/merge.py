from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..storage.repositories import normalize_doi, normalize_title
from .models import PaperRecord, SourceName

SOURCE_PRIORITY: dict[str, tuple[SourceName, ...]] = {
    "title": ("wos_export", "wos", "openalex", "crossref", "pdf"),
    "authors": ("wos_export", "wos", "openalex", "crossref", "pdf"),
    "journal": ("wos_export", "wos", "crossref", "openalex", "pdf"),
    "year": ("wos_export", "wos", "crossref", "openalex", "pdf"),
    "abstract": ("wos_export", "openalex", "crossref", "pdf", "wos"),
    "url": ("wos", "wos_export", "openalex", "crossref", "pdf"),
    "citations": ("wos", "openalex", "crossref", "wos_export", "pdf"),
}


@dataclass(frozen=True)
class FieldProvenance:
    value: Any
    source: SourceName


@dataclass(frozen=True)
class MergedPaper:
    identity: str
    doi: str | None
    wos_uid: str | None
    title: str
    authors: tuple[str, ...]
    journal: str | None
    year: int | None
    abstract: str | None
    url: str | None
    citations: int | None
    sources: tuple[PaperRecord, ...]
    provenance: dict[str, tuple[FieldProvenance, ...]]
    weak_match: bool


def weak_fingerprint(record: PaperRecord) -> str:
    first_author = normalize_title(record.authors[0]) if record.authors else ""
    value = f"{normalize_title(record.title)}|{first_author}|{record.year or ''}"
    return hashlib.sha256(value.encode()).hexdigest()


def _group_records(records: list[PaperRecord]) -> list[tuple[list[PaperRecord], bool]]:
    groups: list[tuple[list[PaperRecord], bool]] = []
    doi_groups: dict[str, int] = {}
    uid_groups: dict[str, int] = {}
    weak_groups: dict[str, int] = {}
    for record in records:
        doi = normalize_doi(record.doi)
        uid = record.wos_uid
        weak = weak_fingerprint(record)
        group_index = doi_groups.get(doi) if doi else None
        if group_index is None and uid:
            group_index = uid_groups.get(uid)
        if group_index is None:
            group_index = weak_groups.get(weak)
        used_weak = group_index is not None and doi is None and uid is None
        if group_index is None:
            group_index = len(groups)
            groups.append(([], False))
        group, previous_weak = groups[group_index]
        known_dois = {normalize_doi(item.doi) for item in group if item.doi}
        if doi and known_dois and doi not in known_dois:
            group_index = len(groups)
            groups.append(([], False))
            group, previous_weak = groups[group_index]
            used_weak = False
        group.append(record)
        groups[group_index] = (group, previous_weak or used_weak)
        if doi:
            doi_groups[doi] = group_index
        if uid:
            uid_groups[uid] = group_index
        weak_groups.setdefault(weak, group_index)
    return groups


def _values(group: list[PaperRecord], field: str) -> tuple[FieldProvenance, ...]:
    priorities = SOURCE_PRIORITY[field]
    found: list[FieldProvenance] = []
    seen: set[str] = set()
    for source in priorities:
        for record in group:
            if record.source != source:
                continue
            value = getattr(record, field)
            if value is None or value == () or value == "":
                continue
            key = repr(value)
            if key not in seen:
                found.append(FieldProvenance(value, source))
                seen.add(key)
    return tuple(found)


def _primary(provenance: dict[str, tuple[FieldProvenance, ...]], field: str) -> Any:
    values = provenance[field]
    return None if not values else values[0].value


def merge_records(records: list[PaperRecord]) -> list[MergedPaper]:
    merged: list[MergedPaper] = []
    for group, weak in _group_records(records):
        doi = next((normalize_doi(record.doi) for record in group if record.doi), None)
        uid = next((record.wos_uid for record in group if record.wos_uid), None)
        provenance = {field: _values(group, field) for field in SOURCE_PRIORITY}

        identity = (
            f"doi:{doi}" if doi else f"wos:{uid}" if uid else f"weak:{weak_fingerprint(group[0])}"
        )
        merged.append(
            MergedPaper(
                identity=identity,
                doi=doi,
                wos_uid=uid,
                title=str(_primary(provenance, "title")),
                authors=tuple(_primary(provenance, "authors") or ()),
                journal=_primary(provenance, "journal"),
                year=_primary(provenance, "year"),
                abstract=_primary(provenance, "abstract"),
                url=_primary(provenance, "url"),
                citations=_primary(provenance, "citations"),
                sources=tuple(group),
                provenance=provenance,
                weak_match=weak,
            )
        )
    return merged
