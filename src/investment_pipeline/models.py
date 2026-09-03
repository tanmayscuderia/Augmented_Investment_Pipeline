"""Typed data models shared across pipeline stages.

The Evidence model is the heart of the system: every material factual claim
produced downstream must resolve to one or more Evidence records. Do not pass
plain dicts between stages.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

SeedType = Literal["topic", "batch", "urls"]


class SeedInput(BaseModel):
    type: SeedType
    value: str | list[str]


# ---------------------------------------------------------------------------
# Candidates and signals
# ---------------------------------------------------------------------------

SignalType = Literal[
    "hn_points",
    "hn_comments",
    "recent_launch",
    "github_activity",
    "funding",
    "customer_claim",
    "batch_recency",
]


class Signal(BaseModel):
    """A dated, evidence-backed freshness/community signal for a candidate."""

    type: SignalType
    value: str | float | int
    observed_at: datetime | None = None
    evidence_id: str


class Candidate(BaseModel):
    id: str
    name: str
    normalized_name: str
    website: str | None = None
    normalized_domain: str | None = None
    description: str | None = None
    batch: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    founder_signals: list[str] = Field(default_factory=list)
    freshness_signals: list[Signal] = Field(default_factory=list)
    discovery_score: float | None = None
    discovered_at: datetime = Field(default_factory=utcnow)
    # Structured context used for ranking and research (empty for bare URLs)
    one_liner: str | None = None
    industries: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    team_size: int | None = None
    location: str | None = None
    launched_at: datetime | None = None
    # Transparent audit of how discovery_score was computed
    ranking_components: dict[str, float] | None = None

    def searchable_text(self) -> str:
        parts = [
            self.name,
            self.one_liner or "",
            self.description or "",
            " ".join(self.industries),
            " ".join(self.tags),
            self.batch or "",
        ]
        return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

SourceType = Literal["yc", "company_website", "hacker_news", "web_search", "github", "press"]
Reliability = Literal["first_party", "independent", "community", "aggregator"]


class Evidence(BaseModel):
    id: str  # E001, E002, ...
    company_id: str
    source_type: SourceType
    title: str | None = None
    url: str
    publisher: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    excerpt: str
    content_hash: str
    reliability: Reliability


class RetrievalError(BaseModel):
    url: str
    reason: str


class EvidenceCompleteness(BaseModel):
    company_identity: bool = False
    product: bool = False
    founders: bool = False
    traction: bool = False
    market: bool = False
    competitors: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def coverage_ratio(self) -> float:
        flags = (
            self.company_identity,
            self.product,
            self.founders,
            self.traction,
            self.market,
            self.competitors,
        )
        return round(sum(bool(f) for f in flags) / len(flags), 4)


class EvidenceBundle(BaseModel):
    company_id: str
    candidate: Candidate
    evidence: list[Evidence] = Field(default_factory=list)
    retrieval_errors: list[RetrievalError] = Field(default_factory=list)
    completeness: EvidenceCompleteness = Field(default_factory=EvidenceCompleteness)

    def evidence_by_id(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.evidence}


# ---------------------------------------------------------------------------
# Structured LLM analysis
# ---------------------------------------------------------------------------


class Claim(BaseModel):
    """A single factual or inferential statement.

    inference=False means FACT: it must cite >=1 supplied evidence ID.
    inference=True marks interpretation; citations optional.
    UNKNOWN is expressed as a statement plus membership in unknowns[].
    """

    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    inference: bool = False


class TeamAnalysis(BaseModel):
    founder_summary: list[Claim] = Field(default_factory=list)
    technical_depth: Claim
    prior_startup_experience: Claim | None = None
    founder_market_fit: Claim
    strengths: list[Claim] = Field(default_factory=list)
    concerns: list[Claim] = Field(default_factory=list)
    score: int  # 0-25


class ProductAnalysis(BaseModel):
    plain_english_description: Claim
    target_customer: Claim
    core_workflow: Claim
    pain_severity: Claim
    differentiation: Claim
    expansion_potential: Claim
    score: int  # 0-25


class MarketAnalysis(BaseModel):
    market_description: Claim
    economic_buyer: Claim
    competitive_landscape: list[Claim] = Field(default_factory=list)
    why_now: list[Claim] = Field(default_factory=list)
    market_size_hint: Claim | None = None  # hint only, never invented TAM
    score: int  # 0-20


class TractionAnalysis(BaseModel):
    signals: list[Claim] = Field(default_factory=list)
    freshness: Claim
    evidence_quality: Literal["strong", "moderate", "weak"]
    score: int  # 0-20


class TimingAnalysis(BaseModel):
    why_now: list[Claim] = Field(default_factory=list)
    defensibility: list[Claim] = Field(default_factory=list)
    model_platform_dependency: Claim
    score: int  # 0-10


class Risk(BaseModel):
    risk: str
    severity: Literal["critical", "high", "medium", "low"]
    reasoning: str
    evidence_ids: list[str] = Field(default_factory=list)
    inference: bool = False


class OpenQuestion(BaseModel):
    question: str
    why_it_matters: str
    would_change_recommendation: bool = False


class InvestmentAnalysis(BaseModel):
    company_id: str
    company_name: str
    twenty_second_view: str
    why_it_matters: str
    team: TeamAnalysis
    product: ProductAnalysis
    market: MarketAnalysis
    traction: TractionAnalysis
    timing: TimingAnalysis
    risks: list[Risk] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    recommendation_rationale: list[str] = Field(default_factory=list)  # max 3, enforced
    change_my_mind: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring and recommendation
# ---------------------------------------------------------------------------


class ScoreBreakdown(BaseModel):
    team: int
    product: int
    market: int
    traction: int
    timing: int
    total: int


class Score(BaseModel):
    breakdown: ScoreBreakdown
    evidence_confidence: Literal["HIGH", "MEDIUM", "LOW"]
    coverage_ratio: float


class Recommendation(BaseModel):
    call: Literal["PASS", "WATCH", "TAKE_A_MEETING"]
    score: int
    rationale: list[str]
    override_reason: str | None = None
    change_my_mind: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Thesis configuration
# ---------------------------------------------------------------------------


class ThesisWeights(BaseModel):
    team: int = 25
    product: int = 25
    market: int = 20
    traction: int = 20
    timing_defensibility: int = 10


class RecommendationThresholds(BaseModel):
    take_meeting: int = 80
    watch: int = 65


class ScoringAnchor(BaseModel):
    band: str
    description: str


class DimensionAnchors(BaseModel):
    dimension: str
    max_score: int
    anchors: list[ScoringAnchor] = Field(default_factory=list)


class Thesis(BaseModel):
    id: str
    name: str
    summary: str
    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    weights: ThesisWeights = Field(default_factory=ThesisWeights)
    recommendation_thresholds: RecommendationThresholds = Field(default_factory=RecommendationThresholds)
    scoring_anchors: list[DimensionAnchors] = Field(default_factory=list)

    def anchors_text(self) -> str:
        lines: list[str] = []
        for dim in self.scoring_anchors:
            lines.append(f"{dim.dimension} (0-{dim.max_score}):")
            lines.extend(f"  - {a.band}: {a.description}" for a in dim.anchors)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run bookkeeping
# ---------------------------------------------------------------------------


class Usage(BaseModel):
    llm_calls: int = 0
    search_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def merge(self, other: Usage) -> None:
        self.llm_calls += other.llm_calls
        self.search_calls += other.search_calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens


class RunManifest(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    input: SeedInput
    thesis: str
    candidate_count: int
    models: dict[str, dict[str, Any]]
    sources: list[str]
    usage: Usage = Field(default_factory=Usage)
    pipeline_version: str
    notes: list[str] = Field(default_factory=list)


class CompanyResult(BaseModel):
    """Everything known about one company at the end of a run."""

    candidate: Candidate
    bundle: EvidenceBundle | None = None
    analysis: InvestmentAnalysis | None = None
    analysis_error: str | None = None
    score: Score | None = None
    recommendation: Recommendation | None = None
    memo_path: str | None = None
