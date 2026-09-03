"""Hacker News candidate source (topic mode only).

Searches the public HN Algolia API for topic and Show HN stories, extracts
plausible startup domains, and emits HN-native candidates plus per-domain
community stats. HN engagement is a community/launch signal, never customer
traction.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from investment_pipeline.config import Settings
from investment_pipeline.http import HttpClient
from investment_pipeline.models import Candidate, SeedInput
from investment_pipeline.sourcing.base import SOURCE_HN, CommunityStats, company_name_from_domain
from investment_pipeline.sourcing.dedupe import normalize_domain, normalize_name

log = logging.getLogger(__name__)

HN_SEARCH = "https://hn.algolia.com/api/v1/search"
HN_SEARCH_BY_DATE = "https://hn.algolia.com/api/v1/search_by_date"

# Content platforms / press / mega-cap domains are never startup candidates.
NON_COMPANY_DOMAINS = frozenset(
    [
        "github.com",
        "gist.github.com",
        "gitlab.com",
        "bitbucket.org",
        "medium.com",
        "substack.com",
        "wordpress.com",
        "blogspot.com",
        "dev.to",
        "hashnode.dev",
        "news.ycombinator.com",
        "youtube.com",
        "youtu.be",
        "vimeo.com",
        "twitter.com",
        "x.com",
        "threads.net",
        "reddit.com",
        "old.reddit.com",
        "quora.com",
        "arxiv.org",
        "ssrn.com",
        "wikipedia.org",
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "tiktok.com",
        "producthunt.com",
        "crunchbase.com",
        "pitchbook.com",
        "tracxn.com",
        "cbinsights.com",
        "techcrunch.com",
        "venturebeat.com",
        "theverge.com",
        "bloomberg.com",
        "businesswire.com",
        "prnewswire.com",
        "globenewswire.com",
        "forbes.com",
        "wired.com",
        "arstechnica.com",
        "nytimes.com",
        "wsj.com",
        "ft.com",
        "economist.com",
        "cnbc.com",
        "bbc.com",
        "bbc.co.uk",
        "reuters.com",
        "axios.com",
        "apple.com",
        "google.com",
        "amazon.com",
        "microsoft.com",
        "netflix.com",
        "openai.com",
        "anthropic.com",
        "nvidia.com",
        "intel.com",
        "ibm.com",
        "oracle.com",
        "salesforce.com",
        "adobe.com",
    ]
)

MAX_HN_CANDIDATES = 8


def _parse_created_at(h: dict[str, Any]) -> datetime | None:
    raw = h.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


class HackerNewsSource:
    name = SOURCE_HN

    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings
        self.last_stats: dict[str, CommunityStats] = {}

    async def discover(self, seed: SeedInput) -> list[Candidate]:
        """Return HN-native candidates for a topic seed; stats land in last_stats."""
        self.last_stats = {}
        if seed.type != "topic":
            return []
        hits: list[dict[str, Any]] = []
        queries = (
            (HN_SEARCH, "story"),
            (HN_SEARCH, "show_hn"),
            (HN_SEARCH_BY_DATE, "story"),
        )
        for endpoint, tag in queries:
            data, err = await self.http.get_json(
                endpoint, params={"query": str(seed.value), "tags": tag, "hitsPerPage": 30}
            )
            if err or not isinstance(data, dict):
                log.warning("HN search failed (%s/%s): %s", endpoint, tag, err)
                continue
            hits.extend(data.get("hits") or [])

        by_id = {h["objectID"]: h for h in hits if h.get("objectID")}
        candidates = self._candidates_from_hits(list(by_id.values()))
        log.info("HN topic discovery: %d stories -> %d candidate domains", len(by_id), len(candidates))
        return candidates

    def _candidates_from_hits(self, hits: list[dict[str, Any]]) -> list[Candidate]:
        domain_hits: dict[str, list[dict[str, Any]]] = {}
        for h in hits:
            url = h.get("url")
            if not url:
                continue
            d = normalize_domain(str(url))
            if not d or d in NON_COMPANY_DOMAINS:
                continue
            domain_hits.setdefault(d, []).append(h)

        ranked = sorted(
            domain_hits.items(),
            key=lambda kv: max(s.get("points") or 0 for s in kv[1]),
            reverse=True,
        )[:MAX_HN_CANDIDATES]

        candidates: list[Candidate] = []
        for domain, stories in ranked:
            best = max(stories, key=lambda s: (s.get("points") or 0, s.get("num_comments") or 0))
            created = [_parse_created_at(s) for s in stories]
            created = [c for c in created if c]
            self.last_stats[domain] = CommunityStats(
                points=sum(s.get("points") or 0 for s in stories),
                comments=sum(s.get("num_comments") or 0 for s in stories),
                latest_at=max(created) if created else None,
                stories=len(stories),
            )
            name = company_name_from_domain(domain)
            candidates.append(
                Candidate(
                    id=f"hn-{domain.replace('.', '-')}",
                    name=name,
                    normalized_name=normalize_name(name),
                    website=f"https://{domain}",
                    normalized_domain=domain,
                    description=(
                        f'Surfaced via Hacker News discussion: "{best.get("title") or domain}" '
                        f"({best.get('points') or 0} points, {best.get('num_comments') or 0} comments)."
                    ),
                    source_refs=[f"https://news.ycombinator.com/item?id={best['objectID']}"],
                )
            )
        return candidates
