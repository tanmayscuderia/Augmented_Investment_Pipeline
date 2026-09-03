"""Deterministic recommendation: thresholds + low-evidence meeting gate.

There is no model-controlled fatal-risk override. Critical risks surface in the
memo; the only automatic downgrade is the deterministic evidence gate on
TAKE_A_MEETING (raw score is always reported unmodified).
"""

from __future__ import annotations

from investment_pipeline.models import InvestmentAnalysis, Recommendation, Score, Thesis

LOW_COVERAGE_GATE = 0.5


def recommend(analysis: InvestmentAnalysis, score: Score, thesis: Thesis) -> Recommendation:
    thresholds = thesis.recommendation_thresholds
    total = score.breakdown.total
    call = "TAKE_A_MEETING" if total >= thresholds.take_meeting else ("WATCH" if total >= thresholds.watch else "PASS")
    override_reason: str | None = None
    if call == "TAKE_A_MEETING" and score.coverage_ratio < LOW_COVERAGE_GATE:
        call = "WATCH"
        override_reason = (
            f"Score {total} clears the take-meeting threshold (>= {thresholds.take_meeting}), "
            f"but evidence coverage is {score.coverage_ratio:.0%}, below the "
            f"{LOW_COVERAGE_GATE:.0%} gate for a high-conviction meeting call. The score is "
            "reported unmodified; collect stronger evidence before upgrading the call."
        )
    return Recommendation(
        call=call,  # type: ignore[arg-type]
        score=total,
        rationale=[r for r in analysis.recommendation_rationale if r and r.strip()][:3],
        override_reason=override_reason,
        change_my_mind=list(analysis.change_my_mind),
    )
