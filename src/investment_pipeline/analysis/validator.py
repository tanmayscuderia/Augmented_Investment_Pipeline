"""Deterministic post-model validation: citations, inference rules, bounds.

Runs after every model response. Failures feed a single bounded retry; a second
failure marks that company's analysis as failed and the pipeline continues.
"""

from __future__ import annotations

from pydantic import BaseModel

from investment_pipeline.models import Claim, EvidenceBundle, InvestmentAnalysis

DIMENSION_BOUNDS = {
    "team": (0, 25),
    "product": (0, 25),
    "market": (0, 20),
    "traction": (0, 20),
    "timing": (0, 10),
}


def _iter_claims(model: BaseModel, prefix: str = ""):
    for name, value in model:
        path = f"{prefix}{name}" if prefix else name
        if isinstance(value, Claim):
            yield path, value
        elif isinstance(value, BaseModel):
            yield from _iter_claims(value, prefix=f"{path}.")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, Claim):
                    yield f"{path}[{i}]", item
                elif isinstance(item, BaseModel):
                    yield from _iter_claims(item, prefix=f"{path}[{i}].")


def validate_analysis(analysis: InvestmentAnalysis, bundle: EvidenceBundle) -> list[str]:
    valid_ids = set(bundle.evidence_by_id())
    errors: list[str] = []
    for path, claim in _iter_claims(analysis):
        unknown = [eid for eid in claim.evidence_ids if eid not in valid_ids]
        if unknown:
            errors.append(f"{path}: unknown evidence ids {unknown}")
        if not claim.inference and not claim.evidence_ids:
            errors.append(f"{path}: factual claim (inference=false) has no evidence id")
        if not claim.statement.strip():
            errors.append(f"{path}: empty statement")
    for dim, (lo, hi) in DIMENSION_BOUNDS.items():
        value = getattr(analysis, dim).score
        if not isinstance(value, int) or value < lo or value > hi:
            errors.append(f"{dim}.score {value!r} outside bounds {lo}-{hi}")
    if not analysis.recommendation_rationale:
        errors.append("recommendation_rationale is empty (need 1-3 reasons)")
    if len(analysis.recommendation_rationale) > 3:
        errors.append("recommendation_rationale has more than 3 items")
    if not analysis.twenty_second_view.strip():
        errors.append("twenty_second_view is empty")
    return errors
