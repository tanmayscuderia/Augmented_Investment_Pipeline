"""Shared helpers for candidate sourcing adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SOURCE_YC = "yc"
SOURCE_HN = "hacker_news"
SOURCE_URLS = "urls"


class SourcingError(RuntimeError):
    """A primary sourcing source is unavailable (pipeline degrades gracefully)."""


@dataclass
class CommunityStats:
    """Aggregated HN discussion stats for one company domain.

    These are community/launch traction signals, never customer traction.
    """

    points: int = 0
    comments: int = 0
    latest_at: datetime | None = None
    stories: int = 0


def company_name_from_domain(domain: str) -> str:
    labels = [label for label in domain.split(".") if label]
    root = labels[0] if labels and labels[0] != "www" else (labels[1] if len(labels) > 1 else domain)
    name = root.replace("-", " ").replace("_", " ").strip()
    return (name[:1].upper() + name[1:]) if name else domain
