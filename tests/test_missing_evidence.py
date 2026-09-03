"""Missing founder evidence must degrade gracefully, never crash or invent."""

import asyncio

from investment_pipeline.analysis.analyzer import FixtureAnalyzer
from investment_pipeline.analysis.thesis import load_thesis
from investment_pipeline.analysis.validator import validate_analysis
from investment_pipeline.config import ROOT
from investment_pipeline.memo.renderer import MemoRenderer
from investment_pipeline.models import CompanyResult, EvidenceBundle
from investment_pipeline.scoring.recommendation import recommend
from investment_pipeline.scoring.score import compute_score

THESIS = load_thesis()
FIXTURE = ROOT / "tests" / "fixtures" / "eval_bundles" / "nofounder_bundle.json"


def _result_bundle_and_analysis():
    b = EvidenceBundle.model_validate_json(FIXTURE.read_text())
    analysis = asyncio.run(FixtureAnalyzer().analyze(b.candidate, b, THESIS))
    return b, analysis


def test_fixture_has_no_founder_evidence():
    b, _ = _result_bundle_and_analysis()
    assert b.completeness.founders is False


def test_analysis_survives_and_flags_the_gap():
    b, analysis = _result_bundle_and_analysis()
    assert validate_analysis(analysis, b) == []
    assert any("founder" in u.lower() for u in analysis.unknowns)
    assert analysis.team.founder_summary == []


def test_memo_renders_with_explicit_unknowns():
    b, analysis = _result_bundle_and_analysis()
    score = compute_score(analysis, b)
    rec = recommend(analysis, score, THESIS)
    run_meta = {
        "run_id": "test",
        "pipeline_version": "0.1.0",
        "model": "fixture",
        "prompt_version": "v1",
        "generated_at": "2026-09-03",
        "input_desc": "test",
        "thesis_name": THESIS.name,
    }
    memo = MemoRenderer().render_memo(
        CompanyResult(candidate=b.candidate, bundle=b, analysis=analysis, score=score, recommendation=rec),
        run_meta,
    )
    assert "Insufficient public evidence on founders" in memo
    assert "Unknowns" in memo
    assert "Scorecard" in memo
