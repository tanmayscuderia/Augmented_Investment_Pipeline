"""Optional Tavily web-search enrichment (analysis-time, not sourcing).

At most three queries per company: founders background, competitors/alternatives,
funding/launch/customers. Entirely skipped when TAVILY_API_KEY is absent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from investment_pipeline.config import Settings
from investment_pipeline.http import HttpClient
from investment_pipeline.models import Candidate, RetrievalError, utcnow
from investment_pipeline.research.website import EvidenceDraft
from investment_pipeline.sourcing.dedupe import normalize_domain

log = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_QUERIES_PER_COMPANY = 3
MAX_RESULTS_PER_QUERY = 3

PRESS_DOMAINS = frozenset(
    [
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
    ]
)


class TavilyUnavailable(RuntimeError):
    pass


@dataclass
class SearchHit:
    title: str
    url: str
    content: str


async def tavily_search(http: HttpClient, settings: Settings, query: str, max_results: int) -> list[SearchHit]:
    res = await http.post(
        TAVILY_SEARCH_URL,
        json_body={"query": query, "max_results": max_results, "search_depth": "basic"},
        headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
    )
    if not res.ok:
        raise TavilyUnavailable(f"HTTP {res.status} {res.error or ''}")
    try:
        data = json.loads(res.content)
    except json.JSONDecodeError as exc:
        raise TavilyUnavailable(f"invalid JSON: {exc}") from exc
    return [
        SearchHit(
            title=str(r.get("title") or ""),
            url=str(r.get("url") or ""),
            content=str(r.get("content") or "")[:600],
        )
        for r in data.get("results", [])
    ]


async def enrichment_searches(
    http: HttpClient, candidate: Candidate, settings: Settings
) -> tuple[list[EvidenceDraft], list[RetrievalError], int]:
    """Returns (drafts, errors, queries_run). No-ops without an API key."""
    if not settings.tavily_api_key:
        return [], [], 0

    queries = (
        f'"{candidate.name}" founders background startup',
        f'"{candidate.name}" competitors alternatives',
        f'"{candidate.name}" funding launch customers revenue',
    )
    drafts: list[EvidenceDraft] = []
    errors: list[RetrievalError] = []
    seen_urls: set[str] = set()
    queries_run = 0

    for query in queries:
        try:
            hits = await tavily_search(http, settings, query, settings.max_search_results)
        except TavilyUnavailable as exc:
            errors.append(RetrievalError(url=TAVILY_SEARCH_URL, reason=str(exc)))
            log.warning("Tavily unavailable, skipping remaining enrichment: %s", exc)
            break
        queries_run += 1
        taken = 0
        for hit in hits:
            if taken >= MAX_RESULTS_PER_QUERY or len(drafts) >= settings.max_web_search_evidence:
                break
            domain = normalize_domain(hit.url)
            if not domain or domain == candidate.normalized_domain or domain in seen_urls:
                continue
            seen_urls.add(domain)
            taken += 1
            press = domain in PRESS_DOMAINS
            drafts.append(
                EvidenceDraft(
                    source_type="press" if press else "web_search",
                    url=hit.url,
                    title=hit.title or hit.url,
                    publisher=domain,
                    published_at=None,
                    retrieved_at=utcnow(),
                    excerpt=hit.content[: settings.max_evidence_chars] or "(no content snippet returned)",
                    reliability="independent" if press else "aggregator",
                )
            )
    log.info("web enrichment: %d queries -> %d sources for %s", queries_run, len(drafts), candidate.name)
    return drafts, errors, queries_run
