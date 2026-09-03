"""Shared async HTTP client: filesystem cache, bounded retries, polite headers.

All network access funnels through here so caching, retries, concurrency
bounds, and call accounting happen in exactly one place.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from investment_pipeline.config import Settings
from investment_pipeline.models import utcnow

log = logging.getLogger(__name__)

_RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content: str
    retrieved_at: datetime
    from_cache: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300


def _cache_key(url: str, params: dict[str, Any] | None, json_body: dict[str, Any] | None) -> str:
    material = json.dumps([url, sorted((params or {}).items()), json_body], sort_keys=True, default=str)
    return hashlib.sha256(material.encode()).hexdigest()


class HttpClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._semaphore: asyncio.Semaphore | None = None
        self.search_calls = 0  # HN / Tavily API calls (usage accounting)
        self.page_fetches = 0  # plain page fetches
        self.cache_hits = 0

    @property
    def semaphore(self) -> asyncio.Semaphore:
        # Created lazily so it binds to the running event loop.
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_fetches)
        return self._semaphore

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cache: bool = True,
        api: bool = False,
    ) -> FetchResult:
        return await self._request("GET", url, params=params, headers=headers, cache=cache, api=api)

    async def post(
        self,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cache: bool = False,
        api: bool = True,
    ) -> FetchResult:
        return await self._request("POST", url, json_body=json_body, headers=headers, cache=cache, api=api)

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        api: bool = True,
    ) -> tuple[Any, str | None]:
        res = await self.get(url, params=params, cache=True, api=api)
        if not res.ok:
            return None, res.error or f"HTTP {res.status}"
        try:
            return json.loads(res.content), None
        except json.JSONDecodeError as exc:
            return None, f"invalid JSON: {exc}"

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params=None,
        json_body=None,
        headers=None,
        cache: bool = True,
        api: bool = False,
    ) -> FetchResult:
        cache_path = self.settings.cache_dir / "http" / f"{_cache_key(url, params, json_body)}.json"
        if cache:
            hit = self._read_cache(cache_path)
            if hit is not None:
                self.cache_hits += 1
                return FetchResult(**hit, from_cache=True)
        async with self.semaphore:
            result = await self._send(method, url, params, json_body, headers)
        if cache and result.ok:
            self._write_cache(cache_path, result)
        if api:
            self.search_calls += 1
        else:
            self.page_fetches += 1
        return result

    async def _send(self, method, url, params, json_body, headers) -> FetchResult:
        backoff = [0.5, 1.5]
        last_error = "request failed"
        merged = {"User-Agent": self.settings.user_agent, **(headers or {})}
        for attempt in range(self.settings.http_retries + 1):
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=self.settings.http_timeout_seconds
                ) as client:
                    resp = await client.request(method, url, params=params, json=json_body, headers=merged)
                if resp.status_code in _RETRY_STATUS and attempt < self.settings.http_retries:
                    await asyncio.sleep(backoff[min(attempt, len(backoff) - 1)])
                    continue
                return FetchResult(
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    content=resp.text,
                    retrieved_at=utcnow(),
                )
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.settings.http_retries:
                    await asyncio.sleep(backoff[min(attempt, len(backoff) - 1)])
        return FetchResult(url=url, final_url=url, status=0, content="", retrieved_at=utcnow(), error=last_error)

    def _read_cache(self, path) -> dict | None:
        try:
            if not path.is_file():
                return None
            rec = json.loads(path.read_text())
            retrieved = datetime.fromisoformat(rec["retrieved_at"])
            if utcnow() - retrieved > timedelta(hours=self.settings.cache_ttl_hours):
                return None
            rec["retrieved_at"] = retrieved
            return rec
        except Exception:  # noqa: BLE001 - cache must never break a fetch
            return None

    def _write_cache(self, path, result: FetchResult) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "url": result.url,
                        "final_url": result.final_url,
                        "status": result.status,
                        "content": result.content,
                        "retrieved_at": result.retrieved_at.isoformat(),
                        "error": result.error,
                    }
                )
            )
        except OSError as exc:
            log.debug("cache write failed for %s: %s", path, exc)
