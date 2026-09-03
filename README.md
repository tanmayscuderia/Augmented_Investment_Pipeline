# AI-Augmented Investment Pipeline

Evidence-grounded first-pass triage for seed-stage investments. Given a topic, a
YC batch, or a list of URLs, it finds 10–20 relevant startups, collects public
evidence for each, runs one evidence-constrained structured analysis per
company, applies a single configured investment thesis, computes a
deterministic 0–100 score, and emits a one-page Markdown memo ending in
**PASS / WATCH / TAKE A MEETING**.

Every material factual claim in every memo points back to collected evidence:
a URL, a source, and a retrieval timestamp. The LLM never supplies facts.

## Demo result

`make sample` runs the committed sample configuration end to end:

```bash
uv run pipeline run --topic "AI agents for SMBs" --limit 15 --run-id sample_run
```

and produces `outputs/sample_run/` with `run.json`, `candidates.json`,
`evidence/`, `analyses/`, `memos/`, and a ranked `INDEX.md`.

## Investment thesis

Configured in `thesis/ai_workflow_automation.yaml` (not hard-coded, not prose): 
seed-stage AI-native B2B companies automating recurring, high-cost
knowledge-work workflows where an identifiable economic buyer can observe
measurable ROI in weeks. Favor: narrow workflow wedges, recurring workflows,
technical founders, early shipping evidence, expansion into a system of
action. Penalize: generic AI wrappers, unclear buyers, weak switching costs,
foundation-model feature risk, services disguised as software. The YAML also
carries the scoring anchors (rubric bands) the model must use for subscores,
and the recommendation thresholds (TAKE_A_MEETING ≥ 80, WATCH ≥ 65).

## Architecture

```text
              ┌────────────────┐
              │  Seed Input    │  topic | YC batch | URL list
              └───────┬────────┘
      ┌───────────────▼────────────────┐
      │ Sourcing (discovery only)      │
      │  YC: yc-oss index + BM25       │   deterministic, no LLM
      │  HN: topic + Show HN search    │
      └───────┬────────────────────────┘
              │ normalize + dedupe (domain, then name; no embeddings)
              │ discovery ranking: 0.5 relevance + 0.2 freshness
              │                    + 0.2 community + 0.1 completeness
      ┌───────▼────────────────────────┐
      │ Research (evidence collection) │
      │  YC canonical profile page     │
      │  company site: home + ≤3 pages │  link-discovery, not fixed paths
      │  HN per-company signals        │
      │  optional Tavily (≤3 queries)  │
      └───────┬────────────────────────┘
              │ EvidenceBundle: E001…, content hashes, completeness
      ┌───────▼────────────────────────┐
      │ Structured LLM analysis (JSON) │  evidence-constrained prompt
      └───────┬────────────────────────┘
              │ citation validator (IDs resolve; FACT ⇒ ≥1 evidence)
      ┌───────▼────────────────────────┐
      │ Deterministic score + call     │  Python owns the number
      └───────┬────────────────────────┘
              │
      ┌───────▼────────────────────────┐
      │ Jinja memo + INDEX.md          │  no LLM in rendering
      └────────────────────────────────┘
```

**Sourcing vs research, explicitly:** YC and Hacker News are the only primary
candidate *sources*. Company websites, HN enrichment, and optional Tavily are
evidence *enrichment* for candidates that already exist.

## Why YC + HN

YC's directory provides consistent identity, description, batch, and team-size
signals, accessed here through the public yc-oss JSON mirror of YC's Algolia
index (discovery/indexing only — every YC evidence item cites the canonical
`ycombinator.com/companies/<slug>` URL). Hacker News provides timestamped
public launch/community signals through a documented API. I deliberately chose
depth and traceability across two sources over shallow integrations with
Product Hunt (token-gated GraphQL, commercial-use restrictions), Crunchbase
(paywalled), or X (anti-bot, ToS risk). Discovery ranking is deterministic
BM25 + boosts; an LLM reranker was deliberately not built because retrieval
quality did not require it. If it ever does, that will be a logged decision,
not architecture for its own sake.

## Quick start

```bash
uv sync
cp .env.example .env        # set OPENAI_API_KEY (DeepSeek by default)
uv run pipeline run --topic "AI agents for SMBs"
```

Without a key the pipeline still runs end to end using a clearly-labeled
deterministic fixture analyzer (`--offline` forces it): useful for smoke
tests, never for real memos. `run.json` always records provider, base_url,
model, prompt version, token usage, and API call counts.

## Configuration

`.env` (see `.env.example`). The analysis client is one OpenAI-compatible
client: DeepSeek by default (`OPENAI_BASE_URL=https://api.deepseek.com`,
`ANALYSIS_MODEL=deepseek-v4-flash`); point it at OpenAI by changing those two
values. `TAVILY_API_KEY` is optional; enrichment is skipped gracefully
without it. Knobs for limits, cache TTL, HTTP timeout, and excerpt sizes are
documented there.

## Example commands

```bash
# three input modes
uv run pipeline run --topic "AI agents for SMBs"
uv run pipeline run --batch W25
uv run pipeline run --urls examples/urls.txt

# replayable stages
uv run pipeline source  --topic "AI agents for SMBs"   # discovery only
uv run pipeline research --run outputs/<run>           # evidence only
uv run pipeline analyze --run outputs/<run>            # LLM only, offline from evidence
uv run pipeline analyze --evidence outputs/<run>/evidence
uv run pipeline render  --run outputs/<run>            # memos from analyses, no LLM

# evals
uv run pipeline eval            # static cases (no network)
uv run pipeline eval --live     # + LLM-backed cases (needs key)
```

## Output structure

```text
outputs/<run_id>/
    run.json          # input, thesis, models, usage, notes
    candidates.json   # post-dedupe, post-ranking candidates + score components
    evidence/<id>.json   # EvidenceBundle per company (persisted before analysis)
    analyses/<id>.json   # structured analysis JSON
    memos/<id>.md        # one-page memo
    INDEX.md             # ranked table with links
```

## Evidence & provenance model

`Evidence` carries: id (`E001…`), company, source type (`yc`,
`company_website`, `hacker_news`, `web_search`, `github`, `press`), title, URL,
publisher, published/retrieved timestamps, excerpt, content hash, and
reliability (`first_party`, `independent`, `community`, `aggregator`).
Company-website claims are first-party: the memo can say "the company claims
500 businesses" — never "500 paying customers". HN points are labeled
community/launch signals everywhere, never customer traction. A programmatic
completeness check (identity/product/founders/traction/market/competitors)
produces evidence confidence HIGH/MEDIUM/LOW — no fake precision percentages.

## Scoring methodology

The model returns bounded subscores (team 0–25, product 0–25, market 0–20,
traction 0–20, timing/defensibility 0–10) guided by the YAML rubric bands.
Python sums them; the LLM never computes the final number. The score is never
capped or mutated for sparse evidence: attractiveness and evidence confidence
are independent. The one deterministic adjustment is a gate on the call: a
TAKE_A_MEETING from a company whose evidence coverage is below 50% is
downgraded to WATCH with a recorded reason — the score stays on display.
There is no model-controlled fatal-risk override; critical risks surface in
"What could kill this".

## Reliability and failure handling

A single failure never kills a run: YC down → continue on HN; site 403/SSL →
recorded `retrieval_errors`, continue; Tavily absent → skipped; LLM/schema/
citation failure → one bounded retry with the validator's complaints, then the
company is marked failed and the rest continue. HTTP is bounded (15s timeout,
2 retries, backoff, concurrency 5) with a filesystem cache (`.cache/`, 24h
TTL, SHA-256 keys) — reruns mostly hit cache (a 5-company rerun made 0 API
calls).

## Evaluation

`evals/cases.yaml` holds six cases; checks are code, YAML documents intent.
Static cases run offline: citation integrity, factual-claim-without-citation
rejection, and the thin-evidence gate (a 97/100 on 33% evidence must stay
score 97 / confidence LOW / call WATCH). Live cases run a real model against
fixture bundles: no invented founder backgrounds, no unsourced numeric TAM,
and a mandatory defensibility concern for an obvious wrapper. The harness was
built from a real observed failure: HN enrichment once matched a company named
Trope with stories about narrative *tropes* — see `process/AI_WORKLOG.md`.

## How AI was used

| Area | AI involvement | Human decision |
|---|---|---|
| Architecture | AI-assisted plan | Scope cut to filesystem pipeline; 12-point plan review |
| Data sources | AI verified live | Human approved YC+HN-only boundary |
| YC / HN adapters | AI-generated | Reviewed normalization, dedupe, error handling |
| Evidence schema | Collaborative | Human-owned provenance design |
| Thesis + anchors | AI-critiqued | Human-owned content and weights |
| Analysis prompt | AI-drafted | Human reviewed constraints, v1-only policy |
| Tests & evals | AI-assisted | Human picked failure cases (incl. live ones) |
| Memos | Generated by pipeline | Format manually chosen |

Details in `process/DECISIONS.md` and `process/AI_WORKLOG.md`.

## Deliberately not built

No frontend, no FastAPI, no database, no Redis/queues, no vector store, no
LangGraph/CrewAI or multi-agent theatre, no LinkedIn scraping, no model
router, no LLM reranker (yet), no dashboards. Fifteen candidates do not
justify infrastructure; filesystem artifacts make every stage inspectable and
replayable.

## Repository walkthrough

```text
src/investment_pipeline/
    models.py          # all typed schemas; dicts never cross stage boundaries
    config.py          # .env + Settings
    http.py            # cached, bounded async HTTP (one funnel)
    sourcing/          # yc, hackernews, urls, dedupe, ranking (BM25)
    research/          # website, hn_enrichment, search (Tavily), evidence, orchestrator
    analysis/          # prompts, analyzer (OpenAI-compatible + fixture), validator, thesis
    scoring/           # score, recommendation (thresholds + evidence gate)
    memo/              # Jinja templates + deterministic renderer
    pipeline.py        # stages + orchestration + replay
    cli.py             # Typer: run/source/research/analyze/render/eval
    evals.py           # eval harness
prompts/               # versioned system prompts (v1 only, until a real failure)
thesis/                # investment thesis + scoring anchors (YAML)
evals/                 # cases + committed results
tests/                 # 31 offline tests + fixtures
process/               # decisions, AI work log, session exports
```
