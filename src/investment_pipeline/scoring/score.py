"""Deterministic scoring. Python owns the final number - never the LLM.

The investment score is NEVER capped or mutated for sparse evidence: investment
attractiveness and evidence confidence are independent dimensions.
"""

from __future__ import annotations

from investment_pipeline.models import EvidenceBundle, InvestmentAnalysis, Score, ScoreBreakdown

DIMENSION_BOUNDS = {
    "team": (0, 25),
    "product": (0, 25),
    "market": (0, 20),
    "traction": (0, 20),
    "timing": (0, 10),
}


def evidence_confidence(coverage: float) -> str:
    if coverage >= 0.83:
        return "HIGH"
    if coverage >= 0.5:
        return "MEDIUM"
    return "LOW"


def compute_score(analysis: InvestmentAnalysis, bundle: EvidenceBundle) -> Score:
    def clamped(dim: str) -> int:
        lo, hi = DIMENSION_BOUNDS[dim]
        return max(lo, min(hi, int(getattr(analysis, dim).score)))

    values = {dim: clamped(dim) for dim in DIMENSION_BOUNDS}
    coverage = bundle.completeness.coverage_ratio
    return Score(
        breakdown=ScoreBreakdown(**values, total=sum(values.values())),
        evidence_confidence=evidence_confidence(coverage),  # type: ignore[arg-type]
        coverage_ratio=coverage,
    )
