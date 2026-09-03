"""Pipeline orchestration and replayable stage functions.

Stages: source -> research -> analyze -> score/recommend -> render.
Each stage persists artifacts under outputs/<run_id>/ so any later stage can
be replayed without touching the web or an LLM.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from pydantic import BaseModel

from investment_pipeline.analysis.analyzer import AnalysisError, BaseAnalyzer, make_analyzer
from investment_pipeline.analysis.thesis import load_thesis
from investment_pipeline.config import Settings, get_settings
from investment_pipeline.http import HttpClient
from investment_pipeline.memo.renderer import MemoRenderer
from investment_pipeline.models import (
    Candidate,
    CompanyResult,
    EvidenceBundle,
    InvestmentAnalysis,
    RunManifest,
    SeedInput,
    Thesis,
    Usage,
    utcnow,
)
from investment_pipeline.research.orchestrator import research_candidate
from investment_pipeline.scoring.recommendation import recommend
from investment_pipeline.scoring.score import compute_score
from investment_pipeline.sourcing.base import SOURCE_HN, SOURCE_URLS, SOURCE_YC
from investment_pipeline.sourcing.dedupe import dedupe_candidates
from investment_pipeline.sourcing.hackernews import HackerNewsSource
from investment_pipeline.sourcing.ranking import RankingContext, rank_candidates, thesis_query_text
from investment_pipeline.sourcing.urls import load_url_candidates
from investment_pipeline.sourcing.yc import YCSource

log = logging.getLogger(__name__)


def _version() -> str:
    try:
        return metadata.version("investment-pipeline")
    except metadata.PackageNotFoundError:
        from investment_pipeline import __version__

        return __version__


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "run"


def make_run_id(settings: Settings, seed: SeedInput, override: str | None = None) -> str:
    if override:
        base = slugify(override)
    else:
        label = seed.value if isinstance(seed.value, str) else ",".join(seed.value)
        base = f"{datetime.now(UTC):%Y-%m-%d}-{slugify(label)}"
    if not (settings.outputs_dir / base).exists():
        return base
    n = 2
    while (settings.outputs_dir / f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


def _input_description(seed: SeedInput) -> str:
    return f"{seed.type}: {seed.value if isinstance(seed.value, str) else ', '.join(seed.value)}"


class CandidatesFile(BaseModel):
    """Persisted candidates.json shape."""

    run_id: str
    seed: SeedInput
    candidates: list[Candidate]


def _write_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2))


def load_run(run_dir: Path) -> RunManifest | None:
    path = run_dir / "run.json"
    if path.is_file():
        return RunManifest.model_validate_json(path.read_text())
    return None


def _load_bundles(evidence_dir: Path) -> list[EvidenceBundle]:
    bundles: list[EvidenceBundle] = []
    if evidence_dir.is_dir():
        for path in sorted(evidence_dir.glob("*.json")):
            bundles.append(EvidenceBundle.model_validate_json(path.read_text()))
    return bundles


# ---------------------------------------------------------------------------
# Stage: source
# ---------------------------------------------------------------------------


async def source_stage(
    seed: SeedInput, thesis: Thesis, settings: Settings, limit: int
) -> tuple[list[Candidate], list[str], Usage]:
    http = HttpClient(settings)
    usage = Usage()
    sources: list[str] = []

    yc_candidates: list[Candidate] = []
    if seed.type in ("topic", "batch"):
        try:
            yc_candidates = await YCSource(http, settings).candidates(seed)
            sources.append(SOURCE_YC)
        except Exception as exc:  # noqa: BLE001 - graceful degradation
            log.warning("YC sourcing failed, continuing: %s", exc)

    hn_candidates: list[Candidate] = []
    community_stats = {}
    if seed.type == "topic":
        try:
            hn = HackerNewsSource(http, settings)
            hn_candidates = await hn.discover(seed)
            community_stats = hn.last_stats
            if hn_candidates:
                sources.append(SOURCE_HN)
        except Exception as exc:  # noqa: BLE001
            log.warning("HN sourcing failed, continuing: %s", exc)

    url_candidates: list[Candidate] = []
    if seed.type == "urls":
        url_candidates = load_url_candidates(Path(str(seed.value)))
        sources.append(SOURCE_URLS)

    log.info("YC candidates: %d", len(yc_candidates))
    log.info("HN candidates: %d", len(hn_candidates))
    log.info("URL candidates: %d", len(url_candidates))

    merged = dedupe_candidates(yc_candidates + hn_candidates + url_candidates)
    log.info("deduplicated candidates: %d", len(merged))

    if seed.type == "topic":
        context = RankingContext(mode="topic", relevance_query=str(seed.value), community_stats=community_stats)
    elif seed.type == "batch":
        context = RankingContext(mode="batch", relevance_query=thesis_query_text(thesis))
    else:
        context = RankingContext(mode="urls", community_stats=community_stats)
    ranked = rank_candidates(merged, context, thesis)
    retained = ranked[:limit]
    log.info("retained candidates: %d", limit)
    for c in retained:
        log.info("  %.3f  %s (%s)", c.discovery_score or 0.0, c.name, c.normalized_domain or "no-domain")
    usage.search_calls = http.search_calls
    return retained, sources, usage


async def source_only(
    seed: SeedInput,
    *,
    limit: int | None = None,
    run_id: str | None = None,
    thesis_path: Path | None = None,
    settings: Settings | None = None,
) -> Path:
    settings = settings or get_settings()
    thesis = load_thesis(thesis_path)
    final_run_id = make_run_id(settings, seed, run_id)
    run_dir = settings.outputs_dir / final_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    candidates, sources, usage = await source_stage(seed, thesis, settings, limit or settings.default_limit)
    _write_json(run_dir / "candidates.json", CandidatesFile(run_id=final_run_id, seed=seed, candidates=candidates))
    _write_json(
        run_dir / "run.json",
        RunManifest(
            run_id=final_run_id,
            started_at=utcnow(),
            input=seed,
            thesis=thesis.id,
            candidate_count=len(candidates),
            models={"analysis": {}},
            sources=sources,
            usage=usage,
            pipeline_version=_version(),
            notes=["source stage only"],
        ),
    )
    return run_dir


# ---------------------------------------------------------------------------
# Stage: research
# ---------------------------------------------------------------------------


async def research_stage(
    candidates: list[Candidate], settings: Settings, http: HttpClient | None = None
) -> list[EvidenceBundle]:
    http = http or HttpClient(settings)
    gate = asyncio.Semaphore(3)  # companies researched concurrently

    async def one(candidate: Candidate) -> EvidenceBundle:
        async with gate:
            log.info("researching: %s", candidate.name)
            return await research_candidate(http, candidate, settings)

    return list(await asyncio.gather(*(one(c) for c in candidates)))


async def run_research(run_dir: Path, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    cf = CandidatesFile.model_validate_json((run_dir / "candidates.json").read_text())
    http = HttpClient(settings)
    bundles = await research_stage(cf.candidates, settings, http)
    for bundle in bundles:
        _write_json(run_dir / "evidence" / f"{bundle.company_id}.json", bundle)
    log.info("evidence -> %s (%d bundles)", run_dir / "evidence", len(bundles))


# ---------------------------------------------------------------------------
# Stage: analyze
# ---------------------------------------------------------------------------


async def analyze_stage(
    bundles: list[EvidenceBundle], thesis: Thesis, analyzer: BaseAnalyzer
) -> tuple[dict[str, InvestmentAnalysis], dict[str, str]]:
    analyses: dict[str, InvestmentAnalysis] = {}
    failures: dict[str, str] = {}
    for bundle in bundles:
        log.info("analyzing: %s", bundle.candidate.name)
        try:
            analyses[bundle.company_id] = await analyzer.analyze(bundle.candidate, bundle, thesis)
        except AnalysisError as exc:
            failures[bundle.company_id] = str(exc)
            log.error("analysis failed for %s: %s", bundle.candidate.name, exc)
    return analyses, failures


async def run_analyze(
    run_dir: Path,
    *,
    offline: bool = False,
    prompt_version: str = "v1",
    thesis_path: Path | None = None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    thesis = load_thesis(thesis_path)
    bundles = _load_bundles(run_dir / "evidence")
    if not bundles:
        raise FileNotFoundError(f"no evidence bundles under {run_dir / 'evidence'}")
    analyzer = make_analyzer(settings, offline, prompt_version)
    analyses, failures = await analyze_stage(bundles, thesis, analyzer)
    for company_id, analysis in analyses.items():
        _write_json(run_dir / "analyses" / f"{company_id}.json", analysis)
    log.info("analyses -> %s (%d ok, %d failed)", run_dir / "analyses", len(analyses), len(failures))


# ---------------------------------------------------------------------------
# Stage: score + recommend + render
# ---------------------------------------------------------------------------


def render_stage(
    run_dir: Path,
    thesis: Thesis,
    bundles: list[EvidenceBundle],
    analyses: dict[str, InvestmentAnalysis],
    failures: dict[str, str],
    manifest: RunManifest,
    settings: Settings,
) -> list[CompanyResult]:
    renderer = MemoRenderer(settings)
    analysis_meta = manifest.models.get("analysis", {})
    run_meta = {
        "run_id": manifest.run_id,
        "pipeline_version": manifest.pipeline_version,
        "model": str(analysis_meta.get("model", "unknown")),
        "prompt_version": str(analysis_meta.get("prompt_version", "v1")),
        "generated_at": utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "input_desc": _input_description(manifest.input),
        "thesis_name": thesis.name,
    }
    bundle_by_id = {b.company_id: b for b in bundles}
    results: list[CompanyResult] = []

    for company_id, analysis in analyses.items():
        bundle = bundle_by_id[company_id]
        score = compute_score(analysis, bundle)
        rec = recommend(analysis, score, thesis)
        result = CompanyResult(
            candidate=bundle.candidate, bundle=bundle, analysis=analysis, score=score, recommendation=rec
        )
        memo = renderer.render_memo(result, run_meta)
        memo_path = run_dir / "memos" / f"{company_id}.md"
        memo_path.parent.mkdir(parents=True, exist_ok=True)
        memo_path.write_text(memo)
        result.memo_path = str(memo_path.relative_to(run_dir))
        log.info("%s: score %d -> %s", result.candidate.name, score.breakdown.total, rec.call)
        results.append(result)

    for company_id, reason in failures.items():
        bundle = bundle_by_id.get(company_id)
        if bundle:
            results.append(CompanyResult(candidate=bundle.candidate, bundle=bundle, analysis_error=reason))

    results.sort(key=lambda r: (-(r.score.breakdown.total if r.score else -1), r.candidate.name))
    rows = [
        {
            "name": r.candidate.name,
            "link": f"memos/{r.candidate.id}.md",
            "score": r.score.breakdown.total,
            "call": r.recommendation.call,
            "confidence": r.score.evidence_confidence,
        }
        for r in results
        if r.score
    ]
    fail_rows = [
        {"name": r.candidate.name, "reason": (r.analysis_error or "unknown")[:200]} for r in results if r.analysis_error
    ]
    (run_dir / "INDEX.md").write_text(renderer.render_index(run_meta, rows, fail_rows))
    return results


def run_render(run_dir: Path, *, thesis_path: Path | None = None, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    thesis = load_thesis(thesis_path)
    bundles = _load_bundles(run_dir / "evidence")
    analyses: dict[str, InvestmentAnalysis] = {}
    analyses_dir = run_dir / "analyses"
    if analyses_dir.is_dir():
        for path in sorted(analyses_dir.glob("*.json")):
            analysis = InvestmentAnalysis.model_validate_json(path.read_text())
            analyses[analysis.company_id] = analysis
    manifest = load_run(run_dir) or RunManifest(
        run_id=run_dir.name,
        started_at=utcnow(),
        input=SeedInput(type="urls", value="replay"),
        thesis=thesis.id,
        candidate_count=len(bundles),
        models={"analysis": {}},
        sources=[],
        pipeline_version=_version(),
    )
    failures = {b.company_id: "analysis missing" for b in bundles if b.company_id not in analyses}
    render_stage(run_dir, thesis, bundles, analyses, failures, manifest, settings)
    log.info("memos + INDEX -> %s", run_dir)


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------


async def run_pipeline(
    seed: SeedInput,
    *,
    limit: int | None = None,
    offline: bool = False,
    prompt_version: str = "v1",
    run_id: str | None = None,
    thesis_path: Path | None = None,
    settings: Settings | None = None,
) -> Path:
    settings = settings or get_settings()
    thesis = load_thesis(thesis_path)
    limit = limit or settings.default_limit
    final_run_id = make_run_id(settings, seed, run_id)
    run_dir = settings.outputs_dir / final_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = utcnow()
    log.info("run %s: starting (mode=%s, limit=%d)", final_run_id, seed.type, limit)

    candidates, sources, usage = await source_stage(seed, thesis, settings, limit)
    _write_json(run_dir / "candidates.json", CandidatesFile(run_id=final_run_id, seed=seed, candidates=candidates))

    http = HttpClient(settings)
    bundles = await research_stage(candidates, settings, http)
    for bundle in bundles:
        _write_json(run_dir / "evidence" / f"{bundle.company_id}.json", bundle)
    usage.search_calls += http.search_calls

    analyzer = make_analyzer(settings, offline, prompt_version)
    analyses, failures = await analyze_stage(bundles, thesis, analyzer)
    for company_id, analysis in analyses.items():
        _write_json(run_dir / "analyses" / f"{company_id}.json", analysis)
    usage.merge(analyzer.usage)

    analyzer_model = settings.analysis_model if analyzer.provider != "fixture" else "fixture (no LLM)"
    manifest = RunManifest(
        run_id=final_run_id,
        started_at=started,
        finished_at=utcnow(),
        input=seed,
        thesis=thesis.id,
        candidate_count=len(candidates),
        models={
            "analysis": {
                "provider": analyzer.provider,
                "base_url": settings.openai_base_url,
                "model": analyzer_model,
                "prompt_version": prompt_version,
                "temperature": settings.analysis_temperature,
                "thinking": settings.analysis_thinking,
            }
        },
        sources=sources,
        usage=usage,
        pipeline_version=_version(),
        notes=[f"retrieval cache hits: {http.cache_hits}"],
    )
    _write_json(run_dir / "run.json", manifest)

    render_stage(run_dir, thesis, bundles, analyses, failures, manifest, settings)
    log.info(
        "run %s complete: %d analyses, %d failures, %d LLM calls, %d search calls",
        final_run_id,
        len(analyses),
        len(failures),
        usage.llm_calls,
        usage.search_calls,
    )
    return run_dir
