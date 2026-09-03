"""Company website extraction: homepage + up to 3 keyword-selected pages.

Internal pages are chosen by scoring links on the homepage (about, team,
founders, customers, case-studies, ...) rather than blindly requesting fixed
paths. First-party pages prove the company CLAIMS something - reliability
stays first_party and downstream language must stay company-reported.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from investment_pipeline.config import Settings
from investment_pipeline.http import HttpClient
from investment_pipeline.models import Candidate, RetrievalError
from investment_pipeline.sourcing.dedupe import normalize_domain

log = logging.getLogger(__name__)

# anchor-text / path keyword -> selection weight
LINK_KEYWORDS: dict[str, int] = {
    "about": 3,
    "team": 3,
    "founder": 3,
    "case-stud": 3,
    "case_stud": 3,
    "customer": 2,
    "client": 2,
    "company": 2,
    "product": 2,
    "story": 2,
    "pricing": 1,
    "contact": 1,
    "career": 1,
    "blog": 0,
}

_WS = re.compile(r"\s+")


@dataclass
class EvidenceDraft:
    """Evidence before ID assignment."""

    source_type: str
    url: str
    title: str | None
    publisher: str | None
    published_at: datetime | None
    retrieved_at: datetime
    excerpt: str
    reliability: str


def extract_text(html: str) -> str | None:
    """trafilatura first, BeautifulSoup fallback."""
    try:
        import trafilatura

        text = trafilatura.extract(html)
        if text:
            return _WS.sub(" ", text).strip()
    except Exception as exc:  # noqa: BLE001 - extraction must never raise
        log.debug("trafilatura failed: %s", exc)
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        return _WS.sub(" ", text).strip() if text else None
    except Exception:
        return None


def page_title(html: str) -> str | None:
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return _WS.sub(" ", soup.title.string).strip()
    except Exception:
        pass
    return None


def _select_internal_links(html: str, base_url: str, max_pages: int) -> list[str]:
    """Score same-domain links by anchor text + path keywords; return top URLs."""
    soup = BeautifulSoup(html, "html.parser")
    base_host = normalize_domain(base_url) or ""
    scored: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or parsed.path in ("", "/"):
            continue
        if normalize_domain(absolute) != base_host:
            continue
        blob = f"{a.get_text(' ', strip=True).lower()} {parsed.path.lower()}"
        score = sum(weight for kw, weight in LINK_KEYWORDS.items() if kw in blob)
        if score <= 0:
            continue
        scored[parsed.path] = max(scored.get(parsed.path, 0), score)
    ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
    return [urljoin(base_url, path) for path, _ in ranked[:max_pages]]


async def research_website(
    http: HttpClient, candidate: Candidate, settings: Settings
) -> tuple[list[EvidenceDraft], list[RetrievalError]]:
    """Fetch homepage + up to 3 useful internal pages. Never raises."""
    drafts: list[EvidenceDraft] = []
    errors: list[RetrievalError] = []
    if not candidate.website and not candidate.normalized_domain:
        errors.append(RetrievalError(url="", reason="candidate has no website"))
        return drafts, errors

    base_url = candidate.website or f"https://{candidate.normalized_domain}"
    home = await http.get(base_url)
    if not home.ok:
        reason = home.error or f"HTTP {home.status}"
        errors.append(RetrievalError(url=base_url, reason=reason))
        log.warning("homepage unavailable: %s (%s)", base_url, reason)
        return drafts, errors

    html = home.content
    text = extract_text(html)
    if text:
        drafts.append(
            EvidenceDraft(
                source_type="company_website",
                url=home.final_url,
                title=page_title(html) or candidate.name,
                publisher=candidate.normalized_domain,
                published_at=None,
                retrieved_at=home.retrieved_at,
                excerpt=text[: settings.max_evidence_chars],
                reliability="first_party",
            )
        )

    for link in _select_internal_links(html, home.final_url, max_pages=3):
        sub = await http.get(link)
        if not sub.ok:
            reason = sub.error or f"HTTP {sub.status}"
            errors.append(RetrievalError(url=link, reason=reason))
            log.warning("page unavailable: %s (%s)", link, reason)
            continue
        sub_text = extract_text(sub.content)
        if not sub_text or len(sub_text) < 80:
            continue
        drafts.append(
            EvidenceDraft(
                source_type="company_website",
                url=sub.final_url,
                title=page_title(sub.content) or link,
                publisher=candidate.normalized_domain,
                published_at=None,
                retrieved_at=sub.retrieved_at,
                excerpt=sub_text[: settings.max_evidence_chars],
                reliability="first_party",
            )
        )
    return drafts, errors
