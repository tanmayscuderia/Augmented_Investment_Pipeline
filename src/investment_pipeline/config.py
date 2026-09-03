"""Environment-driven configuration.

A tiny .env loader plus a frozen Settings dataclass. Filesystem artifacts are
the data store: HTTP cache under .cache/, run artifacts under outputs/.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from investment_pipeline import __version__

ROOT = Path(__file__).resolve().parents[2]


def _load_env(path: Path) -> None:
    """Load KEY=VALUE lines from `path`; never override the real environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # LLM (OpenAI-compatible; DeepSeek by default, OpenAI by swapping base_url+model)
    openai_api_key: str | None
    openai_base_url: str
    analysis_model: str
    analysis_temperature: float
    # Optional enrichment
    tavily_api_key: str | None
    # Filesystem
    cache_dir: Path
    cache_ttl_hours: float
    outputs_dir: Path
    prompts_dir: Path
    # Cost / volume controls
    default_limit: int
    max_search_results: int
    max_web_search_evidence: int
    max_evidence_chars: int
    prompt_excerpt_chars: int
    prompt_total_chars: int
    # HTTP hygiene
    http_timeout_seconds: float
    http_retries: int
    max_concurrent_fetches: int
    user_agent: str


def get_settings() -> Settings:
    _load_env(ROOT / ".env")
    return Settings(
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_base_url=_env("OPENAI_BASE_URL", "https://api.deepseek.com"),
        analysis_model=_env("ANALYSIS_MODEL", "deepseek-v4-flash"),
        analysis_temperature=_env_float("ANALYSIS_TEMPERATURE", 0.2),
        tavily_api_key=_env("TAVILY_API_KEY"),
        cache_dir=Path(_env("CACHE_DIR", str(ROOT / ".cache"))),
        cache_ttl_hours=_env_float("CACHE_TTL_HOURS", 24.0),
        outputs_dir=Path(_env("OUTPUTS_DIR", str(ROOT / "outputs"))),
        prompts_dir=ROOT / "prompts",
        default_limit=_env_int("DEFAULT_LIMIT", 15),
        max_search_results=_env_int("MAX_SEARCH_RESULTS", 5),
        max_web_search_evidence=_env_int("MAX_WEB_SEARCH_EVIDENCE", 8),
        max_evidence_chars=_env_int("MAX_EVIDENCE_CHARS", 6000),
        prompt_excerpt_chars=_env_int("PROMPT_EXCERPT_CHARS", 1000),
        prompt_total_chars=_env_int("PROMPT_TOTAL_CHARS", 18000),
        http_timeout_seconds=_env_float("HTTP_TIMEOUT_SECONDS", 15.0),
        http_retries=_env_int("HTTP_RETRIES", 2),
        max_concurrent_fetches=_env_int("MAX_CONCURRENT_FETCHES", 5),
        user_agent=f"investment-pipeline/{__version__} (evidence-grounded research take-home)",
    )
