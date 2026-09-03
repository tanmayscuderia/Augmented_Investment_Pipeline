"""Evidence assembly: deterministic E001... IDs, dedupe, hashing, completeness."""

from __future__ import annotations

import hashlib
import logging

from investment_pipeline.config import Settings
from investment_pipeline.models import (
    Candidate,
    Evidence,
    EvidenceBundle,
    EvidenceCompleteness,
    RetrievalError,
)
from investment_pipeline.research.website import EvidenceDraft

log = logging.getLogger(__name__)

_FOUNDER_HINTS = ("founder", "co-found", "cofound", "founded by", "ceo", "cto", "chief executive", "previously at")
_COMPETITOR_HINTS = ("competitor", "alternative", "versus", " vs ", "compete", "market share", "landscape", "incumbent")
_MARKET_HINTS = ("market", "industry", "target segment", "spend", "buyers")
_TRACTION_HINTS = ("funding", "raised", "seed", "series a", "customers", "revenue", "launch", "hiring", "backed")


class EvidenceBuilder:
    """Collects drafts, assigns stable IDs, dedupes, computes the bundle."""

    def __init__(self, company_id: str, settings: Settings):
        self.company_id = company_id
        self.settings = settings
        self._evidence: list[Evidence] = []
        self._seen: set[tuple[str, str]] = set()

    def add(self, draft: EvidenceDraft) -> str | None:
        excerpt = (draft.excerpt or "").strip()
        if len(excerpt) < 40:  # too thin to be useful evidence
            return None
        excerpt = excerpt[: self.settings.max_evidence_chars]
        digest = hashlib.sha256(excerpt.encode()).hexdigest()
        key = (draft.url, digest)
        if key in self._seen:
            return None
        self._seen.add(key)
        evidence_id = f"E{len(self._evidence) + 1:03d}"
        self._evidence.append(
            Evidence(
                id=evidence_id,
                company_id=self.company_id,
                source_type=draft.source_type,  # type: ignore[arg-type]
                title=draft.title,
                url=draft.url,
                publisher=draft.publisher,
                published_at=draft.published_at,
                retrieved_at=draft.retrieved_at,
                excerpt=excerpt,
                content_hash=digest,
                reliability=draft.reliability,  # type: ignore[arg-type]
            )
        )
        return evidence_id

    def ids(self, source_type: str | None = None) -> list[str]:
        return [e.id for e in self._evidence if source_type is None or e.source_type == source_type]

    def build(self, candidate: Candidate, retrieval_errors: list[RetrievalError]) -> EvidenceBundle:
        return EvidenceBundle(
            company_id=candidate.id,
            candidate=candidate,
            evidence=self._evidence,
            retrieval_errors=retrieval_errors,
            completeness=_completeness(self._evidence),
        )


def _completeness(evidence: list[Evidence]) -> EvidenceCompleteness:
    comp = EvidenceCompleteness()
    for e in evidence:
        blob = f"{e.title or ''} {e.excerpt}".lower()
        if e.source_type in ("yc", "company_website"):
            comp.company_identity = True
            comp.product = True
        if any(h in blob for h in _FOUNDER_HINTS):
            comp.founders = True
        if e.source_type == "hacker_news" or any(h in blob for h in _TRACTION_HINTS):
            comp.traction = True
        if e.source_type in ("web_search", "press"):
            if any(h in blob for h in _MARKET_HINTS):
                comp.market = True
            if any(h in blob for h in _COMPETITOR_HINTS):
                comp.competitors = True
    return comp
