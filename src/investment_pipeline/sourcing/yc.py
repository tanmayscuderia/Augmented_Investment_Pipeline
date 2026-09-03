"""Y Combinator candidate source.

Discovery/indexing uses the public yc-oss JSON mirror of YC's directory
(https://github.com/yc-oss/api, refreshed daily from YC's public Algolia index).
All YC *evidence* downstream cites the canonical ycombinator.com/companies/<slug>
URL, never the mirror. The mirror is an indexing optimization only.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from investment_pipeline.config import Settings
from investment_pipeline.http import HttpClient
from investment_pipeline.models import Candidate, SeedInput
from investment_pipeline.sourcing.base import SOURCE_YC, SourcingError
from investment_pipeline.sourcing.dedupe import normalize_domain, normalize_name
from investment_pipeline.sourcing.ranking import BM25, tokenize

log = logging.getLogger(__name__)

YC_DATASET_URL = "https://yc-oss.github.io/api/companies/all.json"
TOPIC_PREFILTER_KEEP = 50


def _row_text(row: dict[str, Any]) -> str:
    parts = [
        row.get("name") or "",
        row.get("one_liner") or "",
        row.get("long_description") or "",
        row.get("industry") or "",
        row.get("subindustry") or "",
        " ".join(row.get("industries") or []),
        " ".join(row.get("tags") or []),
    ]
    return " ".join(p for p in parts if p)


def _row_recency(row: dict[str, Any]) -> int:
    return int(row.get("launched_at") or 0)


class YCSource:
    name = SOURCE_YC

    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings

    async def candidates(self, seed: SeedInput) -> list[Candidate]:
        data = await self._dataset()
        if seed.type == "batch":
            wanted = str(seed.value).strip().upper()
            rows = [r for r in data if str(r.get("batch") or "").upper() == wanted]
            log.info("YC batch %s: %d companies", wanted, len(rows))
            return [self._to_candidate(r) for r in rows]
        if seed.type == "topic":
            rows = self._topic_prefilter(data, str(seed.value), keep=TOPIC_PREFILTER_KEEP)
            log.info("YC topic prefilter: %d/%d companies retained", len(rows), len(data))
            return [self._to_candidate(r) for r in rows]
        return []

    async def _dataset(self) -> list[dict[str, Any]]:
        data, err = await self.http.get_json(YC_DATASET_URL, api=False)
        if err or not isinstance(data, list):
            raise SourcingError(f"YC dataset unavailable: {err or 'unexpected payload'}")
        return data

    def _topic_prefilter(self, rows: list[dict[str, Any]], topic: str, keep: int) -> list[dict[str, Any]]:
        corpus = [tokenize(_row_text(r)) for r in rows]
        scores = BM25(corpus).scores(topic)
        order = sorted(range(len(rows)), key=lambda i: (scores[i], _row_recency(rows[i])), reverse=True)
        return [rows[i] for i in order if scores[i] > 0][:keep]

    def _to_candidate(self, row: dict[str, Any]) -> Candidate:
        name = str(row.get("name") or row.get("slug") or "Unknown")
        website = row.get("website") or None
        one_liner = (row.get("one_liner") or "").strip() or None
        long_desc = (row.get("long_description") or "").strip() or None
        description = " ".join(x for x in (one_liner, long_desc) if x) or None
        if description and len(description) > 1500:
            description = description[:1500] + "…"
        launched_raw = row.get("launched_at")
        launched_at = datetime.fromtimestamp(int(launched_raw), tz=UTC) if launched_raw else None
        slug = str(row.get("slug") or row.get("id") or name.lower().replace(" ", "-"))
        canonical = row.get("url") or f"https://www.ycombinator.com/companies/{slug}"
        industries = list(row.get("industries") or [])
        if row.get("industry") and row["industry"] not in industries:
            industries.append(row["industry"])
        return Candidate(
            id=slug,
            name=name,
            normalized_name=normalize_name(name),
            website=website,
            normalized_domain=normalize_domain(website),
            description=description,
            one_liner=one_liner,
            batch=row.get("batch") or None,
            source_refs=[canonical],
            industries=industries,
            tags=[str(t) for t in (row.get("tags") or [])],
            team_size=row.get("team_size"),
            location=row.get("all_locations") or None,
            launched_at=launched_at,
        )
