"""Offline replay: analyze from persisted evidence, render from analyses."""

import asyncio

from helpers import bundle, candidate, evidence
from investment_pipeline.analysis.thesis import load_thesis
from investment_pipeline.models import SeedInput
from investment_pipeline.pipeline import CandidatesFile, run_analyze, run_render

THESIS = load_thesis()


def test_analyze_and_render_replay_offline(tmp_path):
    run_dir = tmp_path / "run"
    c = candidate()
    b = bundle(
        c,
        [
            evidence(
                1,
                c.id,
                "yc",
                "https://www.ycombinator.com/companies/acme",
                "Acme builds AI bookkeeping for small businesses. Batch W25.",
            ),
            evidence(
                2,
                c.id,
                "company_website",
                "https://acme.com",
                "Acme automates bookkeeping for small businesses.",
                publisher="acme.com",
            ),
            evidence(
                3,
                c.id,
                "hacker_news",
                "https://news.ycombinator.com/item?id=9",
                "Show HN: Acme - 40 points, 12 comments.",
                reliability="community",
                publisher="Hacker News",
            ),
        ],
        flags={
            "company_identity": True,
            "product": True,
            "founders": False,
            "traction": True,
            "market": False,
            "competitors": False,
        },
    )
    (run_dir / "evidence").mkdir(parents=True)
    (run_dir / "evidence" / f"{c.id}.json").write_text(b.model_dump_json())
    (run_dir / "candidates.json").write_text(
        CandidatesFile(run_id="run", seed=SeedInput(type="urls", value="x"), candidates=[c]).model_dump_json()
    )

    asyncio.run(run_analyze(run_dir, offline=True))
    assert (run_dir / "analyses" / f"{c.id}.json").exists()

    run_render(run_dir)
    memo = (run_dir / "memos" / f"{c.id}.md").read_text()
    index = (run_dir / "INDEX.md").read_text()
    assert "Acme" in memo and "Scorecard" in memo and "fixture" in memo.lower()
    assert "Acme" in index and "| Rank |" in index
    # replay used no network: the run was fully served from persisted artifacts
    assert "[E001]" in memo and "[E003]" in memo
