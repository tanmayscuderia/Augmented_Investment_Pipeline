"""Per-candidate research orchestration: YC profile -> website -> HN -> Tavily."""

from __future__ import annotations

import logging

from investment_pipeline.config import Settings
from investment_pipeline.http import HttpClient
from investment_pipeline.models import Candidate, EvidenceBundle, RetrievalError, Signal, utcnow
from investment_pipeline.research.evidence import EvidenceBuilder
from investment_pipeline.research.hn_enrichment import enrich_hn
from investment_pipeline.research.search import enrichment_searches
from investment_pipeline.research.website import EvidenceDraft, extract_text, research_website

log = logging.getLogger(__name__)


def _canonical_yc_url(candidate: Candidate) -> str | None:
    for ref in candidate.source_refs:
        if "ycombinator.com/companies/" in ref:
            return ref
    return None


async def research_candidate(http: HttpClient, candidate: Candidate, settings: Settings) -> EvidenceBundle:
    builder = EvidenceBuilder(candidate.id, settings)
    errors: list[RetrievalError] = []

    # 1) YC profile. Canonical ycombinator.com URL is the citation; the yc-oss
    #    structured record is a transparent fallback when the page cannot be extracted.
    yc_url = _canonical_yc_url(candidate)
    if yc_url:
        res = await http.get(yc_url)
        text = extract_text(res.content) if res.ok else None
        if text and len(text) >= 80:
            builder.add(
                EvidenceDraft(
                    source_type="yc",
                    url=res.final_url,
                    title=f"{candidate.name} - YC company profile",
                    publisher="Y Combinator",
                    published_at=None,
                    retrieved_at=res.retrieved_at,
                    excerpt=text[: settings.max_evidence_chars],
                    reliability="first_party",
                )
            )
        else:
            if not res.ok:
                errors.append(RetrievalError(url=yc_url, reason=res.error or f"HTTP {res.status}"))
            fields = [
                f"Company: {candidate.name}",
                f"One-liner: {candidate.one_liner or 'n/a'}",
                f"Description: {candidate.description or 'n/a'}",
                f"Batch: {candidate.batch or 'n/a'}",
                f"Industries: {', '.join(candidate.industries) or 'n/a'}",
                f"Tags: {', '.join(candidate.tags) or 'n/a'}",
                f"Team size: {candidate.team_size or 'unknown'}",
                f"Location: {candidate.location or 'unknown'}",
            ]
            builder.add(
                EvidenceDraft(
                    source_type="yc",
                    url=yc_url,
                    title=f"{candidate.name} - YC company profile (structured record)",
                    publisher="Y Combinator",
                    published_at=None,
                    retrieved_at=utcnow(),
                    excerpt=(
                        " | ".join(fields) + " [Structured record from the public yc-oss "
                        "index of YC's directory; the profile page itself could not be extracted.]"
                    ),
                    reliability="first_party",
                )
            )
        yc_ids = builder.ids("yc")
        if yc_ids and candidate.batch and candidate.launched_at:
            candidate.freshness_signals.append(
                Signal(
                    type="batch_recency",
                    value=candidate.batch,
                    observed_at=candidate.launched_at,
                    evidence_id=yc_ids[0],
                )
            )

    # 2) Company website (first-party claims)
    drafts, site_errors = await research_website(http, candidate, settings)
    errors.extend(site_errors)
    for draft in drafts:
        builder.add(draft)

    # 3) Hacker News enrichment (community/launch signals)
    drafts, specs, hn_errors = await enrich_hn(http, candidate, settings)
    errors.extend(hn_errors)
    hn_ids: list[str | None] = [builder.add(d) for d in drafts]
    for spec in specs:
        eid = hn_ids[spec.draft_index] if spec.draft_index < len(hn_ids) else None
        if eid:
            candidate.freshness_signals.append(
                Signal(type=spec.type, value=spec.value, observed_at=spec.observed_at, evidence_id=eid)  # type: ignore[arg-type]
            )

    # 4) Optional Tavily enrichment (silently skipped without a key)
    drafts, search_errors, _ = await enrichment_searches(http, candidate, settings)
    errors.extend(search_errors)
    for draft in drafts:
        builder.add(draft)

    bundle = builder.build(candidate, errors)
    log.info(
        "%s: %d evidence items, coverage %.2f, %d retrieval errors",
        candidate.name,
        len(bundle.evidence),
        bundle.completeness.coverage_ratio,
        len(errors),
    )
    return bundle
