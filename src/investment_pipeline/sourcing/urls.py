"""URL-list seed mode: one company per line, '#' comments allowed."""

from __future__ import annotations

import logging
from pathlib import Path

from investment_pipeline.models import Candidate
from investment_pipeline.sourcing.base import company_name_from_domain
from investment_pipeline.sourcing.dedupe import normalize_domain, normalize_name

log = logging.getLogger(__name__)


def load_url_candidates(path: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url = line if "://" in line else f"https://{line}"
        domain = normalize_domain(url)
        if not domain:
            log.warning("urls line %d: cannot parse '%s' - skipped", lineno, line)
            continue
        name = company_name_from_domain(domain)
        candidates.append(
            Candidate(
                id=f"url-{domain.replace('.', '-')}",
                name=name,
                normalized_name=normalize_name(name),
                website=url,
                normalized_domain=domain,
                source_refs=[url],
            )
        )
    log.info("URL seeds: %d candidates from %s", len(candidates), path)
    return candidates
