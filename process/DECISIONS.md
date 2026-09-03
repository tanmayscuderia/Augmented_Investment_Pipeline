# Engineering decisions

Each entry: decision, context, rejected alternative. All from this build.

## D1 — Filesystem artifacts are the data store

Every stage persists JSON/Markdown under `outputs/<run_id>/`; HTTP cache is
`.cache/`. No database.

Rejected: SQLite / Postgres. 15 candidates and stage-replay do not need a
query engine; plain files make runs diffable, committable, and inspectable
with `cat`.

## D2 — One OpenAI-compatible analyzer, DeepSeek by default

A single client (`OpenAIAnalyzer`) with configurable `base_url` + `model`.
Defaults: `https://api.deepseek.com` + `deepseek-v4-flash`. Switching to
OpenAI = two env vars, zero code.

Rejected: Anthropic fallback, provider routing, retries across vendors. The
assignment rewards simplicity and reproducibility, not multi-model resiliency.
Decision made by the repo owner.

## D3 — JSON mode + Pydantic validation, not provider-specific strict schemas

The analysis call uses `response_format={"type": "json_object"}`, a schema
embedded in the prompt, `InvestmentAnalysis.model_validate()` afterwards, and
one bounded retry carrying the validator's errors back to the model.

Rejected: OpenAI structured-output `json_schema` strict mode. It is not
portable to DeepSeek, and D2 requires the same code path to work with both.
Pydantic validation gives the same guarantees with a deterministic validator
we control (citation resolution, bounds, rationale limits).

## D4 — yc-oss is the discovery index; canonical YC URLs are the evidence

The 10MB yc-oss JSON mirror (refreshed daily from YC's public Algolia index)
feeds BM25 discovery. YC evidence items cite
`ycombinator.com/companies/<slug>`; when the profile page cannot be extracted,
the evidence is built from the structured record and says so explicitly in the
excerpt (`[Structured record from the public yc-oss index ...]`).

Rejected: citing yc-oss URLs in memos (reviewers should see canonical YC
provenance); scraping ycombinator.com search (JS directory, fragile, slow).

## D5 — Deterministic sourcing; no LLM reranker (yet)

Topic mode: hand-rolled BM25 over the YC corpus → top 50 → merge with HN
discovery → deterministic discovery ranking. Batch mode ranks against the
thesis text; URL mode treats input as user-curated (flat relevance).

Rejected: asking an LLM to name startups (hallucination risk, unauditable
sourcing) and LLM reranking of the top 50 (no observed retrieval failure to
justify it). If retrieval quality ever demands it, that is a logged decision
plus an eval — not speculative architecture.

## D6 — Score is never capped; evidence confidence is independent

The investment score is the raw sum of bounded subscores. Evidence coverage
produces a separate HIGH/MEDIUM/LOW confidence. The only automatic adjustment
is on the call: TAKE_A_MEETING with coverage < 0.5 is downgraded to WATCH with
a recorded `override_reason`; the score stays displayed.

Rejected: capping the score for thin evidence (conflates "attractive company"
with "well-evidenced company" and hides information from the reader).
Decision made by the repo owner.

## D7 — No model-controlled fatal-risk override

Critical risks surface in the memo's "What could kill this" and in open
questions. Nothing the model writes can silently change the call.

Rejected: an LLM-judged "fatal risk" override — non-deterministic, and the
same run could flip calls across replays.

## D8 — Link-discovery page selection, not fixed paths

The homepage's internal links are scored by anchor text + path keywords
(about/team/founders/case-studies/customers/...); the top ≤3 are fetched.

Rejected: blindly requesting `/about`, `/team`, `/customers` (misses
`/company`, `/case-studies`, non-root deployments; wastes requests on 404s).
Decision made by the repo owner.

## D9 — Hand-rolled BM25 (~40 lines)

Okapi BM25 in `sourcing/ranking.py`, deterministic, no dependency.

Rejected: `rank-bm25` package (extra dependency for 40 lines of textbook
math) and embedding similarity (the assignment explicitly bans it for
dedup/retrieval at this scale; lexical scoring is auditable).

## D10 — HN story matching: domain first, launch-shaped titles only

After a real failure (see WORKLOG 2026-09-03, "Trope" incident), name-only
HN matching is restricted to launch-shaped titles (`Show HN: <name> ...` or
titles starting with the name). Domain match remains the strong signal.

Rejected: plain word-boundary substring matching — floods common-word names
with unrelated stories and pollutes evidence and signals.

## D11 — FixtureAnalyzer exists for tests only

A deterministic placeholder analyzer, labeled `[Fixture analysis ...]` in
every artifact it touches, selected automatically when no key is set or
`--offline` is passed.

Rejected: committing fixture output as a "sample run". The committed sample
run must be real model output; fixture runs are dev smoke tests.
