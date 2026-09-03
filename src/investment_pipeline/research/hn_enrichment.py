"""Per-company Hacker News enrichment.

Queries: exact company name, company domain, Show HN + name. Matching stories
become community evidence plus typed freshness signals. HN engagement is a
community/launch traction signal - never customer traction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from investment_pipeline.config import Settings
from investment_pipeline.http import HttpClient
from investment_pipeline.models import Candidate, RetrievalError, utcnow
from investment_pipeline.research.website import EvidenceDraft
from investment_pipeline.sourcing.dedupe import normalize_domain

log = logging.getLogger(__name__)

HN_SEARCH = "https://hn.algolia.com/api/v1/search"
MAX_STORIES_PER_COMPANY = 5


@dataclass
class SignalSpec:
    """A signal to attach after evidence IDs are assigned (index-linked)."""

    type: str
    value: str | float | int
    observed_at: datetime | None
    draft_index: int


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _story_matches(hit: dict, candidate: Candidate) -> bool:
    """Domain match is the strong signal. Name-only matching is restricted to
    launch-shaped titles ("Show HN: <name> ..." or "<name> ..."): plain
    substring matching floods common-word names (e.g. a company literally
    called "Trope") with unrelated stories."""
    if candidate.normalized_domain:
        external = normalize_domain(str(hit.get("url") or ""))
        if external and external == candidate.normalized_domain:
            return True
    title = str(hit.get("title") or "").lower()
    name = candidate.normalized_name
    if len(name) < 3:
        return False
    name_re = rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])"
    if not re.search(name_re, title):
        return False
    is_show_hn = bool(re.search(r"show\s+hn", title))
    starts_with_name = bool(re.search(rf"^{name_re}", title))
    return is_show_hn or starts_with_name


async def enrich_hn(
    http: HttpClient, candidate: Candidate, settings: Settings
) -> tuple[list[EvidenceDraft], list[SignalSpec], list[RetrievalError]]:
    errors: list[RetrievalError] = []
    queries = (
        {"query": candidate.name, "tags": "story", "hitsPerPage": 30},
        {"query": candidate.normalized_domain or "", "tags": "story", "hitsPerPage": 30},
        {"query": candidate.name, "tags": "show_hn", "hitsPerPage": 30},
    )
    matched: dict[str, dict] = {}
    query_error: str | None = None
    for params in queries:
        if not params["query"]:
            continue
        data, err = await http.get_json(HN_SEARCH, params=params)
        if err or not isinstance(data, dict):
            query_error = err or "unexpected payload"
            log.warning("HN enrichment query failed (%s): %s", params["query"], query_error)
            continue
        for hit in data.get("hits") or []:
            oid = hit.get("objectID")
            if oid and _story_matches(hit, candidate):
                matched[str(oid)] = hit
    if not matched and query_error:
        errors.append(RetrievalError(url=HN_SEARCH, reason=query_error))

    ranked = sorted(
        matched.values(),
        key=lambda h: (h.get("points") or 0, h.get("num_comments") or 0),
        reverse=True,
    )[:MAX_STORIES_PER_COMPANY]

    drafts: list[EvidenceDraft] = []
    for hit in ranked:
        points = hit.get("points") or 0
        comments = hit.get("num_comments") or 0
        external = str(hit.get("url") or "")
        title = str(hit.get("title") or f"HN story {hit.get('objectID')}")
        created = _parse_dt(hit.get("created_at"))
        excerpt = f'"{title}" - {points} points, {comments} comments'
        if external:
            excerpt += f"; links to {external}"
        if created:
            excerpt += f"; posted {created.date().isoformat()}"
        drafts.append(
            EvidenceDraft(
                source_type="hacker_news",
                url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                title=title,
                publisher="Hacker News",
                published_at=created,
                retrieved_at=utcnow(),
                excerpt=excerpt,
                reliability="community",
            )
        )

    specs: list[SignalSpec] = []
    if drafts:
        best_points = max(range(len(ranked)), key=lambda i: ranked[i].get("points") or 0)
        specs.append(
            SignalSpec(
                "hn_points",
                ranked[best_points].get("points") or 0,
                _parse_dt(ranked[best_points].get("created_at")),
                best_points,
            )
        )
        best_comments = max(range(len(ranked)), key=lambda i: ranked[i].get("num_comments") or 0)
        specs.append(
            SignalSpec(
                "hn_comments",
                ranked[best_comments].get("num_comments") or 0,
                _parse_dt(ranked[best_comments].get("created_at")),
                best_comments,
            )
        )
        now = utcnow()
        for i, hit in enumerate(ranked):
            created = _parse_dt(hit.get("created_at"))
            if created and (now - created) <= timedelta(days=90):
                specs.append(SignalSpec("recent_launch", created.date().isoformat(), created, i))
                break
    return drafts, specs, errors
