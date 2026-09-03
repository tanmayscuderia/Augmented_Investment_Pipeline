"""Deterministic scoring: bounds, sum, and confidence mapping."""

from helpers import bundle, candidate, evidence
from investment_pipeline.evals import _synthetic_analysis
from investment_pipeline.scoring.score import compute_score, evidence_confidence

SCORES = {"team": 20, "product": 20, "market": 15, "traction": 15, "timing": 8}


def _score_with(coverage_ratio: int):
    c = candidate()
    evs = [
        evidence(
            1,
            c.id,
            "yc",
            "https://www.ycombinator.com/companies/acme",
            "Acme builds AI bookkeeping for small businesses. Batch W25.",
        ),
        evidence(2, c.id, "company_website", "https://acme.com", "Acme automates bookkeeping for small businesses."),
        evidence(3, c.id, "hacker_news", "https://news.ycombinator.com/item?id=1", "Show HN: Acme - 50 points."),
        evidence(
            4,
            c.id,
            "web_search",
            "https://press.example.com/acme",
            "Competitors in AI bookkeeping include Booke and Keeper.",
        ),
    ]
    b = bundle(
        c,
        evs,
        flags=None
        if coverage_ratio == 4
        else {
            "company_identity": coverage_ratio >= 1,
            "product": coverage_ratio >= 2,
            "founders": coverage_ratio >= 3,
            "traction": coverage_ratio >= 4,
            "market": coverage_ratio >= 5,
            "competitors": coverage_ratio >= 6,
        },
    )
    return compute_score(_synthetic_analysis(b, SCORES), b)


def test_subscore_bounds_are_clamped():
    c = candidate()
    b = bundle(c, [evidence(1, c.id, "yc", "https://x", "long enough excerpt for the builder" * 2)])
    a = _synthetic_analysis(b, {"team": 99, "product": -5, "market": 99, "traction": 99, "timing": 99})
    s = compute_score(a, b)
    assert s.breakdown.team == 25
    assert s.breakdown.product == 0
    assert s.breakdown.market == 20
    assert s.breakdown.traction == 20
    assert s.breakdown.timing == 10
    assert s.breakdown.total == 75


def test_total_is_sum_of_clamped_subscores():
    s = _score_with(4)
    assert s.breakdown.total == sum(
        [SCORES["team"], SCORES["product"], SCORES["market"], SCORES["traction"], SCORES["timing"]]
    )


def test_evidence_confidence_mapping():
    assert evidence_confidence(1.0) == "HIGH"
    assert evidence_confidence(0.67) == "MEDIUM"
    assert evidence_confidence(0.33) == "LOW"
    assert _score_with(6).evidence_confidence == "HIGH"
    assert _score_with(2).evidence_confidence == "LOW"
