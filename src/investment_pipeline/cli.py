"""Typer CLI.

pipeline run     --topic "AI agents for SMBs" | --batch W25 | --urls urls.txt
pipeline source  / research / analyze / render   (replayable stages)
pipeline eval    (static + live AI eval cases)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from investment_pipeline.models import SeedInput

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Evidence-grounded seed-stage investment triage pipeline (YC + Hacker News).",
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )


def _seed(topic: str | None, batch: str | None, urls: Path | None) -> SeedInput:
    from investment_pipeline.models import SeedInput

    provided = sum(bool(x) for x in (topic, batch, urls))
    if provided != 1:
        raise typer.BadParameter("provide exactly one of --topic, --batch, --urls")
    if topic:
        return SeedInput(type="topic", value=topic)
    if batch:
        return SeedInput(type="batch", value=batch)
    return SeedInput(type="urls", value=str(urls))


@app.command()
def run(
    topic: str | None = typer.Option(None, "--topic", help="Topic query, e.g. 'AI agents for SMBs'."),
    batch: str | None = typer.Option(None, "--batch", help="YC batch, e.g. W25."),
    urls: Path | None = typer.Option(None, "--urls", help="File with one company URL per line."),
    limit: int | None = typer.Option(None, "--limit", help="Candidates to retain (default 15)."),
    offline: bool = typer.Option(False, "--offline", help="Deterministic fixture analyzer; no LLM calls."),
    prompt_version: str = typer.Option("v1", "--prompt-version"),
    run_id: str | None = typer.Option(None, "--run-id", help="Override the output directory name."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Full pipeline: source -> research -> analyze -> score -> memo."""
    _setup_logging(verbose)
    from investment_pipeline.pipeline import load_run, run_pipeline

    seed = _seed(topic, batch, urls)
    run_dir = asyncio.run(
        run_pipeline(seed, limit=limit, offline=offline, prompt_version=prompt_version, run_id=run_id)
    )
    manifest = load_run(run_dir)
    n_candidates = manifest.candidate_count if manifest else 0
    n_analyses = len(list((run_dir / "analyses").glob("*.json")))
    n_memos = len(list((run_dir / "memos").glob("*.md")))
    typer.echo("")
    typer.echo(f"✓ Found {n_candidates} candidates")
    typer.echo("✓ Collected evidence")
    typer.echo(f"✓ Generated {n_analyses} analyses")
    typer.echo(f"✓ Wrote {n_memos} memos")
    typer.echo("")
    typer.echo("Output:")
    typer.echo(str(run_dir / "memos"))
    typer.echo(f"INDEX: {run_dir / 'INDEX.md'}")


@app.command()
def source(
    topic: str | None = typer.Option(None, "--topic"),
    batch: str | None = typer.Option(None, "--batch"),
    urls: Path | None = typer.Option(None, "--urls"),
    limit: int | None = typer.Option(None, "--limit"),
    run_id: str | None = typer.Option(None, "--run-id"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Sourcing only: discovery, dedupe, ranking -> candidates.json."""
    _setup_logging(verbose)
    from investment_pipeline.pipeline import source_only

    run_dir = asyncio.run(source_only(_seed(topic, batch, urls), limit=limit, run_id=run_id))
    typer.echo(f"candidates -> {run_dir / 'candidates.json'}")


@app.command()
def research(
    run_dir: Path = typer.Option(..., "--run", help="Run directory containing candidates.json."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Research only: fetch evidence for persisted candidates."""
    _setup_logging(verbose)
    from investment_pipeline.pipeline import run_research

    asyncio.run(run_research(run_dir))


@app.command()
def analyze(
    run_dir: Path | None = typer.Option(None, "--run", help="Run directory containing evidence/."),
    evidence: Path | None = typer.Option(
        None, "--evidence", help="Evidence directory; analyses are written to the sibling 'analyses/'."
    ),
    offline: bool = typer.Option(False, "--offline"),
    prompt_version: str = typer.Option("v1", "--prompt-version"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Analyze persisted evidence without touching the web."""
    _setup_logging(verbose)
    from investment_pipeline.pipeline import run_analyze

    if (run_dir is None) == (evidence is None):
        raise typer.BadParameter("provide exactly one of --run or --evidence")
    target = run_dir if run_dir else evidence.parent
    asyncio.run(run_analyze(Path(target), offline=offline, prompt_version=prompt_version))
    typer.echo(f"analyses -> {Path(target) / 'analyses'}")


@app.command()
def render(
    run_dir: Path | None = typer.Option(None, "--run", help="Run directory."),
    analyses: Path | None = typer.Option(
        None, "--analyses", help="Analyses directory; memos are written to the sibling 'memos/'."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Render memos + INDEX from persisted analyses (no LLM, no web)."""
    _setup_logging(verbose)
    from investment_pipeline.pipeline import run_render

    if (run_dir is None) == (analyses is None):
        raise typer.BadParameter("provide exactly one of --run or --analyses")
    target = run_dir if run_dir else analyses.parent
    run_render(Path(target))
    typer.echo(f"memos + INDEX -> {Path(target)}")


@app.command(name="eval")
def eval_(
    live: bool = typer.Option(False, "--live", help="Also run LLM-backed cases (needs OPENAI_API_KEY)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run eval cases; write evals/results.json."""
    _setup_logging(verbose)
    from investment_pipeline.evals import run_evals

    results = run_evals(live=live)
    passed = sum(1 for c in results["cases"] if c["status"] == "pass")
    failed = sum(1 for c in results["cases"] if c["status"] == "fail")
    skipped = sum(1 for c in results["cases"] if c["status"] == "skipped")
    for case in results["cases"]:
        typer.echo(f"  [{case['status'].upper():7s}] {case['id']}: {case.get('detail', '')}")
    typer.echo(f"\nevals: {passed} passed, {failed} failed, {skipped} skipped -> evals/results.json")
    raise typer.Exit(code=1 if failed else 0)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
