"""Small AI eval harness.

Static cases exercise the deterministic guards (validator, evidence gate) with
fixture analyses - no network, no LLM. Live cases run a real model against
fixture evidence bundles and apply named checks. Checks are code; cases.yaml
documents intent. Results land in evals/results.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime

import yaml

from investment_pipeline.analysis.analyzer import AnalysisError, BaseAnalyzer, make_analyzer
from investment_pipeline.analysis.thesis import load_thesis
from investment_pipeline.analysis.validator import validate_analysis
from investment_pipeline.config import ROOT, Settings, get_settings
from investment_pipeline.models import (
    Claim,
    EvidenceBundle,
    InvestmentAnalysis,
    MarketAnalysis,
    ProductAnalysis,
    TeamAnalysis,
    Thesis,
    TimingAnalysis,
    TractionAnalysis,
)
from investment_pipeline.scoring.recommendation import recommend
from investment_pipeline.scoring.score import compute_score

log = logging.getLogger(__name__)

CASES_PATH = ROOT / "evals" / "cases.yaml"
RESULTS_PATH = ROOT / "evals" / "results.json"
FIXTURES = ROOT / "tests" / "fixtures" / "eval_bundles"

_NUMERIC_TAM = re.compile(
    r"(\$\s?\d[\d,.]*\s*(billion|million|bn|mm\b|k\b))|(\b\d[\d,.]*\s*(billion|million)\b)",
    re.IGNORECASE,
)

_WRAPPER_KEYWORDS = (
    "wrapper",
    "commodit",
    "differenti",
    "model dependency",
    "platform dependency",
    "foundation model",
    "moat",
    "switching cost",
    "undifferentiated",
)


def _load_bundle(name: str) -> EvidenceBundle:
    return EvidenceBundle.model_validate_json((FIXTURES / name).read_text())


def _market_claims(a: InvestmentAnalysis) -> list[Claim]:
    claims = [a.market.market_description, a.market.economic_buyer]
    claims += list(a.market.competitive_landscape) + list(a.market.why_now)
    if a.market.market_size_hint:
        claims.append(a.market.market_size_hint)
    return [c for c in claims if c]


# ---------------------------------------------------------------------------
# Checks (deterministic, applied to real model output for live cases)
# ---------------------------------------------------------------------------


def check_unsupported_market_size(a: InvestmentAnalysis, bundle: EvidenceBundle) -> tuple[bool, str]:
    evidence = bundle.evidence_by_id()
    for claim in _market_claims(a):
        if _NUMERIC_TAM.search(claim.statement):
            if not claim.evidence_ids:
                return False, f"numeric market claim without citation: '{claim.statement[:90]}'"
            supported = any(
                eid in evidence and _NUMERIC_TAM.search(evidence[eid].excerpt) for eid in claim.evidence_ids
            )
            if not supported:
                return False, (f"numeric market claim cites evidence lacking that figure: '{claim.statement[:90]}'")
    return True, "no unsourced numeric market claims"


def check_missing_founder(a: InvestmentAnalysis, bundle: EvidenceBundle) -> tuple[bool, str]:
    if bundle.completeness.founders:
        return True, "fixture has founder evidence; check trivially satisfied"
    for claim in a.team.founder_summary:
        if not claim.inference:
            return False, f"factual founder claim without founder evidence: '{claim.statement[:90]}'"
    if "founder" not in " ".join(a.unknowns).lower():
        return False, "unknowns[] does not surface the founder-evidence gap"
    return True, "no invented founder background; gap surfaced in unknowns"


def check_wrapper_defensibility(a: InvestmentAnalysis, bundle: EvidenceBundle) -> tuple[bool, str]:
    blob = " ".join(
        [c.statement for c in a.timing.defensibility + a.timing.why_now]
        + [a.timing.model_platform_dependency.statement]
        + [f"{r.risk} {r.reasoning}" for r in a.risks]
    ).lower()
    if any(k in blob for k in _WRAPPER_KEYWORDS):
        return True, "defensibility/model-dependency concern present"
    return False, "no wrapper/defensibility concern raised"


LIVE_CHECKS: dict[str, Callable[[InvestmentAnalysis, EvidenceBundle], tuple[bool, str]]] = {
    "unsupported_market_size": check_unsupported_market_size,
    "missing_founder_information": check_missing_founder,
    "obvious_ai_wrapper": check_wrapper_defensibility,
}


# ---------------------------------------------------------------------------
# Static cases
# ---------------------------------------------------------------------------


def _synthetic_analysis(bundle: EvidenceBundle, scores: dict[str, int]) -> InvestmentAnalysis:
    """Minimal schema-valid analysis citing real evidence IDs."""
    e_ids = [e.id for e in bundle.evidence]
    cited = e_ids[:1]

    def fact(text: str) -> Claim:
        return Claim(statement=text, evidence_ids=cited, confidence="medium")

    def guess(text: str) -> Claim:
        return Claim(statement=text, confidence="low", inference=True)

    return InvestmentAnalysis(
        company_id=bundle.company_id,
        company_name=bundle.candidate.name,
        twenty_second_view="Synthetic analysis for eval purposes.",
        why_it_matters="Synthetic; exercises deterministic scoring and the evidence gate.",
        team=TeamAnalysis(
            founder_summary=[],
            technical_depth=fact("Team evidence cited."),
            founder_market_fit=guess("Unknown."),
            score=scores["team"],
        ),
        product=ProductAnalysis(
            plain_english_description=fact("Product evidence cited."),
            target_customer=guess("Unknown."),
            core_workflow=guess("Unknown."),
            pain_severity=guess("Unknown."),
            differentiation=guess("Unknown."),
            expansion_potential=guess("Unknown."),
            score=scores["product"],
        ),
        market=MarketAnalysis(
            market_description=fact("Market evidence cited."),
            economic_buyer=guess("Unknown."),
            market_size_hint=guess("Unknown."),
            score=scores["market"],
        ),
        traction=TractionAnalysis(
            signals=[],
            freshness=guess("Unknown."),
            evidence_quality="weak",
            score=scores["traction"],
        ),
        timing=TimingAnalysis(
            why_now=[],
            defensibility=[],
            model_platform_dependency=guess("Unknown."),
            score=scores["timing"],
        ),
        recommendation_rationale=["Synthetic rationale for eval."],
    )


def _run_static_case(case: dict) -> dict:
    cid = case["id"]
    thesis = load_thesis()
    if cid == "citation_integrity":
        bundle = _load_bundle("rich_bundle.json")
        analysis = _synthetic_analysis(bundle, {"team": 20, "product": 20, "market": 15, "traction": 15, "timing": 8})
        analysis.team.technical_depth.evidence_ids = ["E999"]  # non-existent
        errors = validate_analysis(analysis, bundle)
        flagged = any("unknown evidence ids" in e for e in errors)
        return {
            "status": "pass" if flagged else "fail",
            "detail": "validator flagged unresolved citation" if flagged else f"not flagged: {errors}",
        }
    if cid == "factual_claim_without_citation":
        bundle = _load_bundle("rich_bundle.json")
        analysis = _synthetic_analysis(bundle, {"team": 20, "product": 20, "market": 15, "traction": 15, "timing": 8})
        analysis.product.plain_english_description.evidence_ids = []
        errors = validate_analysis(analysis, bundle)
        flagged = any("no evidence id" in e for e in errors)
        return {
            "status": "pass" if flagged else "fail",
            "detail": "validator rejected unsupported factual claim" if flagged else f"not flagged: {errors}",
        }
    if cid == "thin_evidence":
        bundle = _load_bundle("thin_bundle.json")
        analysis = _synthetic_analysis(bundle, {"team": 24, "product": 25, "market": 19, "traction": 19, "timing": 10})
        score = compute_score(analysis, bundle)
        rec = recommend(analysis, score, thesis)
        ok = rec.call == "WATCH" and bool(rec.override_reason) and score.evidence_confidence == "LOW"
        return {
            "status": "pass" if ok else "fail",
            "detail": (
                f"score {score.breakdown.total} kept, call downgraded to {rec.call}, "
                f"confidence {score.evidence_confidence}, override={bool(rec.override_reason)}"
            ),
        }
    return {"status": "fail", "detail": f"unknown static case '{cid}'"}


async def _run_live_case(case: dict, analyzer: BaseAnalyzer, thesis: Thesis) -> dict:
    bundle = _load_bundle(case["fixture"])
    try:
        analysis = await analyzer.analyze(bundle.candidate, bundle, thesis)
    except AnalysisError as exc:
        return {"status": "fail", "detail": f"analysis failed: {exc}"}
    check = LIVE_CHECKS[case["id"]]
    ok, detail = check(analysis, bundle)
    return {"status": "pass" if ok else "fail", "detail": detail}


def run_evals(live: bool = False, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    thesis = load_thesis()
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    results: list[dict] = []
    analyzer: BaseAnalyzer | None = None
    for case in cases:
        entry: dict = {"id": case["id"], "mode": case.get("mode", "live"), "expectation": case.get("expectation", {})}
        if case.get("mode") == "static":
            entry.update(_run_static_case(case))
        elif not live or not settings.openai_api_key:
            entry["status"] = "skipped"
            entry["detail"] = "live case: requires --live and OPENAI_API_KEY"
        else:
            analyzer = analyzer or make_analyzer(settings, offline=False, prompt_version="v1")
            entry.update(asyncio.run(_run_live_case(case, analyzer, thesis)))
        results.append(entry)
        log.info("eval %s -> %s", case["id"], entry["status"])

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": settings.analysis_model if settings.openai_api_key else "(none)",
        "cases": results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2))
    return output
