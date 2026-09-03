"""Prompt assembly for the analysis stage (system prompt from prompts/, user
message built deterministically from thesis + candidate + evidence)."""

from __future__ import annotations

import json
import logging

from investment_pipeline.config import Settings
from investment_pipeline.models import Candidate, EvidenceBundle, InvestmentAnalysis, Thesis

log = logging.getLogger(__name__)

SOURCE_LABELS = {
    "yc": "YC",
    "company_website": "Company Website",
    "hacker_news": "Hacker News",
    "web_search": "Web Search",
    "github": "GitHub",
    "press": "Press",
}
_SOURCE_ORDER = {"yc": 0, "company_website": 1, "press": 2, "web_search": 3, "github": 4, "hacker_news": 5}


def load_system_prompt(settings: Settings, version: str) -> str:
    path = settings.prompts_dir / f"analysis_{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt version not found: {path}")
    return path.read_text(encoding="utf-8")


def render_evidence_block(bundle: EvidenceBundle, settings: Settings) -> str:
    lines: list[str] = []
    budget = settings.prompt_total_chars
    ordered = sorted(bundle.evidence, key=lambda e: (_SOURCE_ORDER.get(e.source_type, 9), e.id))
    for e in ordered:
        block = (
            f"[{e.id}]\n"
            f"Source: {SOURCE_LABELS.get(e.source_type, e.source_type)} ({e.reliability})\n"
            f"URL: {e.url}\n"
            f"Retrieved: {e.retrieved_at.date().isoformat()}\n"
            f"Text: {e.excerpt[: settings.prompt_excerpt_chars]}\n"
        )
        if len(block) > budget:
            lines.append("[remaining evidence truncated for length]")
            break
        budget -= len(block)
        lines.append(block)
    return "\n".join(lines)


def build_user_message(candidate: Candidate, bundle: EvidenceBundle, thesis: Thesis, settings: Settings) -> str:
    gaps: list[str] = []
    if not bundle.completeness.founders:
        gaps.append("no founder-related evidence was found")
    if not bundle.completeness.competitors:
        gaps.append("no competitor/market evidence was found")
    if bundle.retrieval_errors:
        gaps.append(f"{len(bundle.retrieval_errors)} source retrieval(s) failed")
    gaps_text = "; ".join(gaps) if gaps else "none"
    schema = json.dumps(InvestmentAnalysis.model_json_schema())

    return f"""THESIS
-------
id: {thesis.id}
name: {thesis.name}
{thesis.summary}

Favor: {", ".join(thesis.positive_signals)}
Penalize: {", ".join(thesis.negative_signals)}

SCORING ANCHORS (use these bands for subscores)
-----------------------------------------------
{thesis.anchors_text()}

COMPANY
-------
name: {candidate.name}
website: {candidate.website or "unknown"}
YC batch: {candidate.batch or "unknown"}
description: {candidate.description or "unknown"}
team size: {candidate.team_size or "unknown"}
location: {candidate.location or "unknown"}

EVIDENCE
--------
{render_evidence_block(bundle, settings)}

KNOWN GAPS
----------
{gaps_text}

TASK
----
Evaluate strictly from the evidence above:
1. Team (score 0-25)
2. Product (score 0-25)
3. Market (score 0-20; market_size_hint must stay qualitative unless a figure appears in evidence)
4. Traction (score 0-20; HN points are community/launch signals, not customer traction)
5. Timing & defensibility (score 0-10)
6. Risks: what could make this a bad seed investment even if the product works?
7. Open questions for diligence (with would_change_recommendation flags)

Also provide:
- twenty_second_view: 2-3 sentence summary a partner can absorb in 20 seconds
- why_it_matters: why this company fits or conflicts with the thesis
- recommendation_rationale: max 3 short, specific reasons for your call
- change_my_mind: what evidence would flip the call
- unknowns: every material gap where public evidence was insufficient

Return a single JSON object exactly matching this schema:
{schema}

Rules: every factual claim (inference=false) MUST cite >=1 evidence ID from the list
above. If evidence is unavailable, say "Unknown - insufficient public evidence" and
add the gap to unknowns. Qualify company-website performance/customer numbers as
"the company claims" unless independently corroborated."""
