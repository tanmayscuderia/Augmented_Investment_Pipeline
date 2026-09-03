"""Deterministic discovery ranking.

discovery_score = 0.50*topic_relevance + 0.20*freshness + 0.20*community + 0.10*data_completeness

- topic_relevance: BM25 over the merged candidate corpus (hand-rolled, no deps).
- freshness: recency decay from YC launch date (neutral floor when unknown).
- community: HN points/comments (community/launch signal, not customer traction).
- data_completeness: fraction of identity fields present.

This score is about which companies to RESEARCH. It is completely separate from
the investment score computed later from evidence.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from investment_pipeline.models import Candidate, Thesis, utcnow
from investment_pipeline.sourcing.base import CommunityStats

log = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
        "we",
        "our",
        "you",
        "your",
        "they",
        "their",
        "this",
        "these",
        "those",
        "what",
        "which",
        "who",
        "will",
        "would",
        "can",
        "could",
        "should",
        "than",
        "then",
        "them",
        "there",
        "here",
        "when",
        "where",
        "why",
        "how",
        "all",
        "any",
        "each",
    ]
)
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split((text or "").lower()) if len(t) >= 2 and t not in _STOPWORDS]


class BM25:
    """Okapi BM25 (k1=1.5, b=0.75) over a pre-tokenized corpus."""

    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.corpus = corpus_tokens
        self.n = len(corpus_tokens)
        total = sum(len(d) for d in corpus_tokens)
        self.avgdl = (total / self.n) if self.n and total else 1.0
        df: Counter[str] = Counter()
        for doc in corpus_tokens:
            df.update(set(doc))
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query_text: str) -> list[float]:
        q = tokenize(query_text)
        out: list[float] = []
        for doc in self.corpus:
            tf = Counter(doc)
            dl = len(doc) or 1
            s = 0.0
            for t in dict.fromkeys(q):
                f = tf.get(t, 0)
                if not f or t not in self.idf:
                    continue
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append(s)
        return out


@dataclass
class RankingContext:
    mode: str  # "topic" | "batch" | "urls"
    relevance_query: str = ""  # topic text or thesis text; empty for urls mode
    community_stats: dict[str, CommunityStats] = field(default_factory=dict)


def _freshness(c: Candidate) -> float:
    if c.launched_at is None:
        return 0.25  # neutral floor: unknown recency should not zero a candidate
    years = max((utcnow() - c.launched_at).days / 365.25, 0.0)
    if years <= 1.0:
        return 1.0
    if years >= 9.0:
        return 0.05
    return round(1.0 - (years - 1.0) * (0.95 / 8.0), 4)


def _community(stats: CommunityStats | None) -> float:
    if stats is None or (stats.points == 0 and stats.comments == 0):
        return 0.1  # neutral floor: absence of HN chatter is not disqualifying
    p = math.log1p(max(stats.points, 0)) / math.log1p(600)
    c = math.log1p(max(stats.comments, 0)) / math.log1p(400)
    return round(min(1.0, 0.7 * p + 0.3 * c), 4)


def _completeness(c: Candidate) -> float:
    checks = (
        bool(c.website),
        bool(c.description),
        bool(c.batch),
        c.launched_at is not None,
        bool(c.team_size and c.team_size > 0),
        bool(c.industries or c.tags),
    )
    return round(sum(checks) / len(checks), 4)


def thesis_query_text(thesis: Thesis) -> str:
    return " ".join([thesis.summary, *thesis.positive_signals])


def rank_candidates(
    candidates: list[Candidate], context: RankingContext, thesis: Thesis | None = None
) -> list[Candidate]:
    if not candidates:
        return []
    corpus = [tokenize(c.searchable_text()) for c in candidates]
    raw = BM25(corpus).scores(context.relevance_query) if context.relevance_query else [0.0] * len(candidates)
    peak = max(raw, default=0.0) or 1.0

    for i, c in enumerate(candidates):
        # urls mode: user-curated input; relevance is not our job there
        relevance = 0.5 if context.mode == "urls" else round(raw[i] / peak, 4)
        components = {
            "topic_relevance": relevance,
            "freshness": _freshness(c),
            "community": _community(context.community_stats.get(c.normalized_domain)),
            "data_completeness": _completeness(c),
        }
        c.ranking_components = components
        c.discovery_score = round(
            0.50 * components["topic_relevance"]
            + 0.20 * components["freshness"]
            + 0.20 * components["community"]
            + 0.10 * components["data_completeness"],
            4,
        )
    return sorted(candidates, key=lambda c: (c.discovery_score or 0.0, c.name), reverse=True)
