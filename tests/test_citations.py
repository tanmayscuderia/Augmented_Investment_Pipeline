"""Citation integrity: every ID resolves; FACT claims need evidence; inferences don't."""

import asyncio

from helpers import bundle, candidate, evidence, full_coverage
from investment_pipeline.analysis.analyzer import FixtureAnalyzer
from investment_pipeline.analysis.thesis import load_thesis
from investment_pipeline.analysis.validator import validate_analysis

THESIS = load_thesis()


def _rich_bundle():
    c = candidate()
    evs = [
        evidence(
            1,
            c.id,
            "yc",
            "https://www.ycombinator.com/companies/acme",
            "Acme builds AI bookkeeping for small businesses. Founded by Ana Lee and Raj Patel.",
        ),
        evidence(
            2,
            c.id,
            "company_website",
            "https://acme.com",
            "Acme automates bookkeeping for small businesses.",
            publisher="acme.com",
        ),
    ]
    return bundle(c, evs, flags=full_coverage())


def test_unresolved_citation_is_flagged():
    b = _rich_bundle()
    from investment_pipeline.evals import _synthetic_analysis

    a = _synthetic_analysis(b, {"team": 20, "product": 20, "market": 15, "traction": 15, "timing": 8})
    a.team.technical_depth.evidence_ids = ["E999"]
    errors = validate_analysis(a, b)
    assert any("unknown evidence ids" in e for e in errors)


def test_factual_claim_without_citation_is_rejected():
    from investment_pipeline.evals import _synthetic_analysis

    b = _rich_bundle()
    a = _synthetic_analysis(b, {"team": 20, "product": 20, "market": 15, "traction": 15, "timing": 8})
    a.product.plain_english_description.evidence_ids = []
    errors = validate_analysis(a, b)
    assert any("no evidence id" in e for e in errors)


def test_inference_without_citation_is_allowed():
    from investment_pipeline.evals import _synthetic_analysis

    b = _rich_bundle()
    a = _synthetic_analysis(b, {"team": 20, "product": 20, "market": 15, "traction": 15, "timing": 8})
    a.product.target_customer.evidence_ids = []  # it is already inference=True
    assert validate_analysis(a, b) == []


def test_fixture_analysis_passes_validation():
    b = _rich_bundle()
    a = asyncio.run(FixtureAnalyzer().analyze(b.candidate, b, THESIS))
    assert validate_analysis(a, b) == []
