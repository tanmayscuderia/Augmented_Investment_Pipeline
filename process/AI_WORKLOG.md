# AI work log

Real events from building this with a coding agent (Cline), newest last.
Nothing here is retrospective or invented; entries are added as things happen.

## 2026-09-03 — spec verification before any code

**Goal:** ground the sourcing design in how the data sources actually behave.

**Asked AI to:** live-probe `yc-oss/api` and the HN Algolia API before
planning, rather than trusting the assignment's description.

**AI found:** yc-oss `all.json` is 10.4MB / 6,201 companies, refreshed daily;
per-company fields include `team_size`, `batch`, `launched_at` — but **no
founder names**. HN hits expose `objectID/points/num_comments/created_at` and
a `show_hn` tag.

**Decision:** founder evidence must come from YC profile pages, company sites,
and search enrichment — and when absent, memos must say "insufficient public
evidence" instead of inventing bios. This later became the
`missing_founder_information` eval case.

## 2026-09-03 — plan review: 12 corrections from the repo owner

**AI proposed:** ~10 planned commits, an `analysis_v2.md` placeholder,
LLM reranking over BM25's top 50, an evidence-coverage score cap, and a
model-controlled fatal-risk override.

**Owner rejected/corrected:** no commit-count targets (reads as manufactured
process); no v2 file until a real failure forces one; no LLM reranking without
an observed retrieval failure; never cap the score (keep score and evidence
confidence independent; gate the call instead); no model-controlled overrides
(critical risks surface in the memo); link-discovery page selection instead of
fixed paths; scoring anchors in the thesis YAML; top-level `unknowns[]`;
"company-reported" qualifier for first-party claims; DeepSeek as the default
model behind one OpenAI-compatible client.

**Artifact:** all twelve applied in the implementation; several are visible in
`scoring/recommendation.py` (the gate) and `research/website.py`
(link discovery).

## 2026-09-03 — small real failure: eval harness wrapped in asyncio.run

`pipeline eval` crashed with `TypeError: An asyncio.Future, a coroutine or an
awaitable is required` — the harness is synchronous and I had reflexively
wrapped it in `asyncio.run`. Removed the wrapper. Nothing subtle; noted
because it was a real crash, not a hypothetical one.

## 2026-09-03 — REAL failure: HN name matching pulled in narrative tropes

**Observed during the first live end-to-end smoke run.** The candidate
"Trope" (trope.ai, AI FDE for ERPs) collected five HN stories about narrative
*tropes* ("The Soap Bubble Trope", "TropeTwist", ...) because enrichment
matched any title containing the word. The pollution flowed into hn_points/hn
comments signals and inflated completeness.founders.

**Fix:** `_story_matches` now treats the company domain as the strong signal
and restricts name-only matching to launch-shaped titles (`Show HN: <name>`
or titles starting with the name). Added
`tests/test_hn_enrichment.py` (common-word names must not match unrelated
stories). Re-ran the live research: Trope's evidence went from 7 items (5
wrong) to 2 clean items.

**Why this matters:** exactly the failure mode evidence-grounded systems are
supposed to catch — the citation validator would not have flagged it, because
the bogus citations resolved to real (but irrelevant) evidence. Source
relevance had to be fixed at the collection layer.

## 2026-09-03 — confirmed degradation behaviors live

`https://sylvian.ai` has an expired TLS certificate. The run recorded
`retrieval_errors: [{url, reason: ConnectError ... CERTIFICATE_VERIFY_FAILED}]`
and produced the memo from the YC structured record instead. A five-company
rerun after the fix made **0 API calls** (all cache hits), confirming the 24h
filesystem cache works as intended.

## 2026-09-03 — tooling note

`ruff --fix` collapsed multiline `frozenset("""...""".split())` blocks into
single-line list literals, producing 400+ character lines. Resolved with
`ruff format` + line-length 120; no behavioral change. Also cleaned two
lint-level issues it surfaced (a forward-referenced type hint needing
`TYPE_CHECKING`, an unused variable).
