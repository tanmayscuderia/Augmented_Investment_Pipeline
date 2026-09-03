"""Recommendation thresholds and the deterministic low-evidence meeting gate."""

import pytest

from helpers import bundle, candidate, coverage, evidence
from investment_pipeline.analysis.thesis import load_thesis
from investment_pipeline.evals import _synthetic_analysis
from investment_pipeline.scoring.recommendation import recommend
from investment_pipeline.scoring.score import compute_score

THESIS = load_thesis()


def _recommend(total: int, n_flags: int):
    c = candidate()
    evs = [
        evidence(1, c.id, "yc", "https://www.ycombinator.com/companies/acme", "Acme AI bookkeeping evidence excerpt.")
    ]
    b = bundle(c, evs, flags=coverage(n_flags))
    scores = {"team": 0, "product": 0, "market": 0, "traction": 0, "timing": 0}
    bounds = {"team": 25, "product": 25, "market": 20, "traction": 20, "timing": 10}
    remaining = total
    for dim, hi in bounds.items():
        take = min(hi, remaining)
        scores[dim] = take
        remaining -= take
    assert remaining == 0, f"total {total} unreachable within bounds"
    a = _synthetic_analysis(b, scores)
    score = compute_score(a, b)
    assert score.breakdown.total == total
    return recommend(a, score, THESIS)


@pytest.mark.parametrize("total,expected", [(80, "TAKE_A_MEETING"), (79, "WATCH"), (65, "WATCH"), (64, "PASS")])
def test_thresholds(total, expected):
    assert _recommend(total, n_flags=6).call == expected


def test_low_evidence_gates_meeting_call_but_keeps_score():
    rec = _recommend(86, n_flags=2)
    assert rec.call == "WATCH"
    assert rec.score == 86  # raw score never capped or mutated
    assert rec.override_reason and "evidence coverage" in rec.override_reason


def test_high_evidence_does_not_gate():
    rec = _recommend(86, n_flags=6)
    assert rec.call == "TAKE_A_MEETING"
    assert rec.override_reason is None
