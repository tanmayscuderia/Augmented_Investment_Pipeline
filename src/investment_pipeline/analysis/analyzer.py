"""LLM analysis: one structured JSON call, deterministic validator, one retry.

A single OpenAI-compatible client (DeepSeek by default; OpenAI by swapping
base_url + model). No provider routing, no agent theatre. FixtureAnalyzer is a
clearly-labeled deterministic placeholder for tests and offline smoke runs.
"""

from __future__ import annotations

import asyncio
import json
import logging

from pydantic import ValidationError

from investment_pipeline.analysis.prompts import build_user_message, load_system_prompt
from investment_pipeline.analysis.validator import validate_analysis
from investment_pipeline.config import Settings, get_settings
from investment_pipeline.models import (
    Candidate,
    Claim,
    EvidenceBundle,
    InvestmentAnalysis,
    MarketAnalysis,
    OpenQuestion,
    ProductAnalysis,
    Risk,
    TeamAnalysis,
    Thesis,
    TimingAnalysis,
    TractionAnalysis,
    Usage,
)

log = logging.getLogger(__name__)


class AnalysisError(RuntimeError):
    pass


def _strip_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


class BaseAnalyzer:
    provider: str = "base"

    def __init__(self) -> None:
        self.usage = Usage()


class OpenAIAnalyzer(BaseAnalyzer):
    provider = "openai-compatible"

    def __init__(self, settings: Settings | None = None, prompt_version: str = "v1"):
        super().__init__()
        from openai import OpenAI

        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise AnalysisError("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=self.settings.openai_api_key, base_url=self.settings.openai_base_url)
        self.prompt_version = prompt_version

    async def analyze(self, candidate: Candidate, bundle: EvidenceBundle, thesis: Thesis) -> InvestmentAnalysis:
        # The SDK call is synchronous; keep the event loop responsive.
        return await asyncio.to_thread(self._analyze_sync, candidate, bundle, thesis)

    def _analyze_sync(self, candidate: Candidate, bundle: EvidenceBundle, thesis: Thesis) -> InvestmentAnalysis:
        system = load_system_prompt(self.settings, self.prompt_version)
        user = build_user_message(candidate, bundle, thesis, self.settings)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error: str | None = None
        raw_content = ""
        for attempt in (1, 2):
            analysis: InvestmentAnalysis | None = None
            try:
                resp = self._client.chat.completions.create(
                    model=self.settings.analysis_model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=self.settings.analysis_temperature,
                    response_format={"type": "json_object"},
                    max_tokens=8000,
                )
                self.usage.llm_calls += 1
                if resp.usage:
                    self.usage.prompt_tokens += resp.usage.prompt_tokens or 0
                    self.usage.completion_tokens += resp.usage.completion_tokens or 0
                    self.usage.total_tokens += resp.usage.total_tokens or 0
                raw_content = _strip_fences(resp.choices[0].message.content or "")
                data = json.loads(raw_content)
                data["company_id"] = candidate.id
                data["company_name"] = candidate.name
                analysis = InvestmentAnalysis.model_validate(data)
                errors = validate_analysis(analysis, bundle)
                if not errors:
                    return analysis
                last_error = "validation failed: " + "; ".join(errors[:8])
            except (json.JSONDecodeError, ValidationError, AttributeError, IndexError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001 - provider SDK errors
                last_error = f"{type(exc).__name__}: {exc}"
            log.warning("analysis attempt %d failed for %s: %s", attempt, candidate.name, last_error)
            if attempt == 1:
                messages = messages + [
                    {"role": "assistant", "content": raw_content or "(empty)"},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous JSON had problems:\n{last_error}\n\n"
                            "Fix every issue. Every factual claim (inference=false) must cite at "
                            "least one evidence ID that exists in the evidence list. If evidence "
                            "is unavailable, set inference=true and say Unknown. Return ONLY the "
                            "corrected JSON object."
                        ),
                    },
                ]
        raise AnalysisError(last_error or "analysis failed")


class FixtureAnalyzer(BaseAnalyzer):
    """Deterministic placeholder for offline tests/smoke runs. Never real memos."""

    provider = "fixture"

    def __init__(self, settings: Settings | None = None, prompt_version: str = "v1"):
        super().__init__()
        self.settings = settings or get_settings()
        self.prompt_version = prompt_version

    async def analyze(self, candidate: Candidate, bundle: EvidenceBundle, thesis: Thesis) -> InvestmentAnalysis:
        self.usage.llm_calls += 1
        by_source: dict[str, list] = {}
        for ev in bundle.evidence:
            by_source.setdefault(ev.source_type, []).append(ev)
        product_ev = (by_source.get("company_website") or by_source.get("yc") or [None])[0]

        def unknown() -> Claim:
            return Claim(statement="Unknown - insufficient public evidence.", confidence="low", inference=True)

        if product_ev and candidate.description:
            product_claim = Claim(
                statement=f"The company describes itself as: {candidate.description[:220]}",
                evidence_ids=[product_ev.id],
                confidence="medium",
            )
        else:
            product_claim = Claim(
                statement="Unknown - insufficient public evidence for a product description.",
                confidence="low",
                inference=True,
            )

        traction_claims = [
            Claim(
                statement=f"Community/launch signal: {s.type} = {s.value}",
                evidence_ids=[s.evidence_id],
                confidence="low",
            )
            for s in candidate.freshness_signals[:5]
        ]
        if not traction_claims:
            traction_claims = [
                Claim(statement="No dated public traction signals found.", confidence="low", inference=True)
            ]
        observed = [s.observed_at for s in candidate.freshness_signals if s.observed_at]
        freshness = Claim(
            statement=(
                f"Latest public community signal observed {max(observed).date().isoformat()}."
                if observed
                else "No dated public community signals found."
            ),
            evidence_ids=[candidate.freshness_signals[0].evidence_id] if candidate.freshness_signals else [],
            confidence="low",
            inference=not bool(observed),
        )

        unknowns = ["Founder backgrounds are not established from collected public evidence."]
        if not bundle.completeness.traction:
            unknowns.append("No reliable adoption, customer, or revenue evidence found.")
        if not bundle.completeness.competitors:
            unknowns.append("Competitive landscape not established from public evidence.")

        return InvestmentAnalysis(
            company_id=candidate.id,
            company_name=candidate.name,
            twenty_second_view=(
                "[Fixture analysis - generated offline without an LLM. Structure only; "
                f"substance requires a real model run.] {candidate.name}: "
                f"{candidate.one_liner or candidate.description or 'description unavailable'}"
            ),
            why_it_matters=(
                "[Fixture] Thesis fit cannot be assessed without a real model analysis; "
                "the collected evidence is listed below for review."
            ),
            team=TeamAnalysis(
                founder_summary=[],
                technical_depth=unknown(),
                founder_market_fit=unknown(),
                concerns=[
                    Claim(
                        statement="Team assessability is limited by available public evidence.",
                        confidence="low",
                        inference=True,
                    )
                ],
                score=10,
            ),
            product=ProductAnalysis(
                plain_english_description=product_claim,
                target_customer=unknown(),
                core_workflow=unknown(),
                pain_severity=unknown(),
                differentiation=unknown(),
                expansion_potential=unknown(),
                score=12,
            ),
            market=MarketAnalysis(
                market_description=Claim(
                    statement=(
                        "Qualitative only: a spend category is implied by the company's own "
                        "positioning; size is not established by collected evidence."
                    ),
                    confidence="low",
                    inference=True,
                ),
                economic_buyer=unknown(),
                market_size_hint=Claim(
                    statement="Unknown - no public market-size evidence collected; qualitative reasoning only.",
                    confidence="low",
                    inference=True,
                ),
                score=10,
            ),
            traction=TractionAnalysis(
                signals=traction_claims,
                freshness=freshness,
                evidence_quality="weak" if bundle.completeness.coverage_ratio < 0.5 else "moderate",
                score=8,
            ),
            timing=TimingAnalysis(
                why_now=[
                    Claim(
                        statement="Timing cannot be judged from a fixture analysis.", confidence="low", inference=True
                    )
                ],
                defensibility=[
                    Claim(
                        statement="Defensibility cannot be judged from a fixture analysis.",
                        confidence="low",
                        inference=True,
                    )
                ],
                model_platform_dependency=unknown(),
                score=5,
            ),
            risks=[
                Risk(
                    risk="Analysis is a placeholder; conclusions are not investment-grade.",
                    severity="high",
                    reasoning="Fixture analyzer was used because no LLM key is configured.",
                    evidence_ids=[],
                    inference=True,
                )
            ],
            open_questions=[
                OpenQuestion(
                    question="Do customers reach production within 30 days?",
                    why_it_matters="Services-heavy onboarding would weaken the software-margin thesis.",
                    would_change_recommendation=True,
                )
            ],
            unknowns=unknowns,
            recommendation_rationale=[
                "Fixture analysis: deterministic placeholder, not investment substance.",
                "Run with a real OPENAI_API_KEY to produce a substantive analysis.",
            ],
            change_my_mind=["Replace this fixture analysis with a real model run."],
        )


def make_analyzer(settings: Settings, offline: bool, prompt_version: str) -> BaseAnalyzer:
    """Real analyzer when a key exists; clearly-labeled fixture otherwise."""
    if not offline and settings.openai_api_key:
        return OpenAIAnalyzer(settings, prompt_version=prompt_version)
    if not offline:
        log.warning("no OPENAI_API_KEY set - falling back to FixtureAnalyzer (placeholder analyses)")
    return FixtureAnalyzer(settings, prompt_version=prompt_version)
