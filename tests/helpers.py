"""Deterministic in-memory builders for candidates, evidence, and bundles."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from investment_pipeline.models import (
    Candidate,
    Evidence,
    EvidenceBundle,
    EvidenceCompleteness,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def candidate(**overrides: Any) -> Candidate:
    defaults: dict[str, Any] = dict(
        id="acme",
        name="Acme",
        normalized_name="acme",
        website="https://acme.com",
        normalized_domain="acme.com",
        description="AI bookkeeping for small businesses.",
        batch="W25",
        source_refs=["https://www.ycombinator.com/companies/acme"],
    )
    defaults.update(overrides)
    return Candidate(**defaults)


def evidence(
    idx: int,
    company_id: str,
    stype: str,
    url: str,
    excerpt: str,
    reliability: str = "first_party",
    publisher: str | None = None,
    published: datetime | None = None,
) -> Evidence:
    excerpt = excerpt.strip()
    return Evidence(
        id=f"E{idx:03d}",
        company_id=company_id,
        source_type=stype,  # type: ignore[arg-type]
        title=f"Evidence {idx}",
        url=url,
        publisher=publisher,
        published_at=published,
        retrieved_at=T0,
        excerpt=excerpt,
        content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
        reliability=reliability,  # type: ignore[arg-type]
    )


def full_coverage() -> dict[str, bool]:
    return dict(
        company_identity=True,
        product=True,
        founders=True,
        traction=True,
        market=True,
        competitors=True,
    )


def coverage(n: int) -> dict[str, bool]:
    keys = ["company_identity", "product", "founders", "traction", "market", "competitors"]
    return {k: (i < n) for i, k in enumerate(keys)}


def bundle(c: Candidate, evidence_list: list[Evidence], flags: dict[str, bool] | None = None) -> EvidenceBundle:
    return EvidenceBundle(
        company_id=c.id,
        candidate=c,
        evidence=evidence_list,
        completeness=EvidenceCompleteness(**(flags or full_coverage())),
    )
