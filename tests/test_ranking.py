"""BM25 and discovery ranking behavior."""

from datetime import UTC, datetime, timedelta

from helpers import candidate
from investment_pipeline.sourcing.ranking import BM25, RankingContext, rank_candidates, tokenize


def test_bm25_ranks_relevant_document_first():
    docs = [tokenize("ai agents for smb bookkeeping"), tokenize("pizza delivery drone app")]
    scores = BM25(docs).scores("ai agents smb")
    assert scores[0] > scores[1] >= 0.0


def test_rank_orders_and_records_components():
    now = datetime.now(UTC)
    fresh = candidate(id="fresh", name="Fresh", launched_at=now - timedelta(days=30))
    stale = candidate(
        id="stale",
        name="Stale",
        launched_at=now - timedelta(days=365 * 10),
        website=None,
        description=None,
        batch=None,
        normalized_domain=None,
        source_refs=["https://example.com"],
    )
    ranked = rank_candidates([stale, fresh], RankingContext(mode="topic", relevance_query="unrelated query terms"))
    assert ranked[0].id == "fresh"
    for c in ranked:
        comps = c.ranking_components
        assert set(comps) == {"topic_relevance", "freshness", "community", "data_completeness"}
        assert all(0.0 <= v <= 1.0 for v in comps.values())
        expected = round(
            0.5 * comps["topic_relevance"]
            + 0.2 * comps["freshness"]
            + 0.2 * comps["community"]
            + 0.1 * comps["data_completeness"],
            4,
        )
        assert c.discovery_score == expected


def test_freshness_neutral_when_unknown():
    c = candidate(launched_at=None)
    ranked = rank_candidates([c], RankingContext(mode="urls"))
    assert ranked[0].ranking_components["freshness"] == 0.25
