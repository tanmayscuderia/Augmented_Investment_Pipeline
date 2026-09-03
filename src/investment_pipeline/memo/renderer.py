"""Deterministic Jinja rendering: memo + INDEX. The memo is never LLM-written."""

from __future__ import annotations

import logging
from typing import Any

from jinja2 import Environment, FileSystemLoader

from investment_pipeline.config import ROOT, Settings, get_settings
from investment_pipeline.models import CompanyResult, Evidence

log = logging.getLogger(__name__)

SOURCE_LABELS = {
    "yc": "YC",
    "company_website": "Company website",
    "hacker_news": "Hacker News",
    "web_search": "Web search",
    "github": "GitHub",
    "press": "Press",
}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _claim_line(claim) -> str:
    if claim is None:
        return ""
    cites = "".join(f" [{eid}]" for eid in claim.evidence_ids)
    return f"{claim.statement}{cites}{' _(inference)_' if claim.inference else ''}"


def _source_line(e: Evidence) -> dict[str, str]:
    return {
        "id": e.id,
        "source_label": SOURCE_LABELS.get(e.source_type, e.source_type),
        "publisher": e.publisher or "unknown",
        "title": (e.title or e.url)[:120],
        "url": e.url,
        "retrieved_at": e.retrieved_at.strftime("%Y-%m-%d %H:%M UTC"),
        "reliability": e.reliability,
    }


def build_memo_context(result: CompanyResult, run: dict[str, Any]) -> dict[str, Any]:
    assert result.analysis and result.score and result.recommendation and result.bundle
    a, score, rec = result.analysis, result.score, result.recommendation
    risks = sorted(a.risks, key=lambda r: _SEVERITY_ORDER.get(r.severity, 9))
    return {
        "candidate": result.candidate,
        "rec": rec,
        "score": score.breakdown.total,
        "score_breakdown": score.breakdown,
        "confidence": score.evidence_confidence,
        "coverage_pct": f"{score.coverage_ratio:.0%}",
        "analysis": a,
        "team": {
            "founders": [_claim_line(c) for c in a.team.founder_summary]
            or ["Insufficient public evidence on founders."],
            "technical_depth": _claim_line(a.team.technical_depth),
            "prior_startup_experience": (
                _claim_line(a.team.prior_startup_experience) if a.team.prior_startup_experience else None
            ),
            "founder_market_fit": _claim_line(a.team.founder_market_fit),
            "strengths": [_claim_line(c) for c in a.team.strengths],
            "concerns": [_claim_line(c) for c in a.team.concerns],
        },
        "product": {
            "description": _claim_line(a.product.plain_english_description),
            "target_customer": _claim_line(a.product.target_customer),
            "core_workflow": _claim_line(a.product.core_workflow),
            "pain_severity": _claim_line(a.product.pain_severity),
            "differentiation": _claim_line(a.product.differentiation),
            "expansion": _claim_line(a.product.expansion_potential),
        },
        "market": {
            "description": _claim_line(a.market.market_description),
            "buyer": _claim_line(a.market.economic_buyer),
            "size_hint": (
                _claim_line(a.market.market_size_hint)
                if a.market.market_size_hint
                else "Unknown - insufficient public evidence."
            ),
            "why_now": [_claim_line(c) for c in a.market.why_now],
            "competitors": [_claim_line(c) for c in a.market.competitive_landscape],
        },
        "traction": {
            "signals": [_claim_line(c) for c in a.traction.signals] or ["No public traction signals collected."],
            "freshness": _claim_line(a.traction.freshness),
            "evidence_quality": a.traction.evidence_quality,
        },
        "timing": {
            "why_now": [_claim_line(c) for c in a.timing.why_now],
            "defensibility": [_claim_line(c) for c in a.timing.defensibility],
            "platform_dependency": _claim_line(a.timing.model_platform_dependency),
        },
        "risks": [
            {
                "severity": r.severity,
                "risk": r.risk,
                "reasoning": r.reasoning,
                "citations": "".join(f" [{eid}]" for eid in r.evidence_ids),
            }
            for r in risks
        ],
        "open_questions": [
            {
                "question": q.question,
                "why_it_matters": q.why_it_matters,
                "would_change_recommendation": q.would_change_recommendation,
            }
            for q in a.open_questions
        ],
        "unknowns": a.unknowns,
        "change_my_mind": rec.change_my_mind or a.change_my_mind,
        "sources": [_source_line(e) for e in result.bundle.evidence],
        "run": run,
    }


class MemoRenderer:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.env = Environment(
            loader=FileSystemLoader(ROOT / "src" / "investment_pipeline" / "memo" / "templates"),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def render_memo(self, result: CompanyResult, run: dict[str, Any]) -> str:
        return self.env.get_template("investment_memo.md.j2").render(**build_memo_context(result, run))

    def render_index(self, run: dict[str, Any], rows: list[dict], failures: list[dict]) -> str:
        return self.env.get_template("index.md.j2").render(rows=rows, failures=failures, **run)
