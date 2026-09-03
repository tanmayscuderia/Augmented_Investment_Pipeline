"""Identifier normalization and candidate deduplication.

Primary key: normalized domain (https://www.foo.ai/about -> foo.ai).
Fallback: normalized company name ("Acme AI, Inc." -> "acme ai").
No embeddings, no fuzzy matching - deterministic string rules only.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from investment_pipeline.models import Candidate

_LEGAL_SUFFIXES = {
    "inc",
    "llc",
    "ltd",
    "co",
    "corp",
    "corporation",
    "company",
    "gmbh",
    "sa",
    "sas",
    "plc",
    "pte",
    "ltda",
    "bv",
    "oy",
    "ab",
    "as",
    "pty",
}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if not v:
        return None
    if "://" not in v:
        v = f"https://{v}"
    host = urlparse(v).netloc.split("@")[-1].split(":")[0].rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_name(name: str) -> str:
    v = name.lower().replace("&", " and ")
    tokens = [t for t in _NON_ALNUM.split(v) if t]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _merge_key(c: Candidate) -> str:
    return c.normalized_domain or f"name:{c.normalized_name}"


def _merge_into(primary: Candidate, other: Candidate) -> Candidate:
    primary.source_refs = _unique(primary.source_refs + other.source_refs)
    primary.founder_signals = _unique(primary.founder_signals + other.founder_signals)
    seen = {(s.type, str(s.value), s.evidence_id) for s in primary.freshness_signals}
    for sig in other.freshness_signals:
        if (sig.type, str(sig.value), sig.evidence_id) not in seen:
            primary.freshness_signals.append(sig)
    if not primary.website:
        primary.website = other.website
    if not primary.normalized_domain:
        primary.normalized_domain = other.normalized_domain
    if not primary.description or len(other.description or "") > len(primary.description):
        primary.description = primary.description or other.description
    if other.description and len(other.description) > len(primary.description or ""):
        primary.description = other.description
    for field in ("one_liner", "batch", "location", "team_size", "launched_at"):
        if getattr(primary, field) is None:
            setattr(primary, field, getattr(other, field))
    for field in ("industries", "tags"):
        setattr(primary, field, _unique(getattr(primary, field) + getattr(other, field)))
    return primary


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    groups: dict[str, list[Candidate]] = {}
    for c in candidates:
        groups.setdefault(_merge_key(c), []).append(c)

    merged: list[Candidate] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        # Prefer the richest identity as primary: YC-sourced > has website > longest description.
        primary = max(
            group,
            key=lambda c: (
                any("ycombinator.com/companies/" in r for r in c.source_refs),
                bool(c.website),
                len(c.description or ""),
            ),
        )
        for other in group:
            if other is not primary:
                primary = _merge_into(primary, other)
        merged.append(primary)
    return merged
