# 01 — Architecture plan review

**Date:** 2026-09-03 · **Agent:** Cline · **Trimmed excerpt of a real session.**
The agent proposed a build plan for the pipeline; the repo owner rejected
several parts of it with reasons, and the agent revised before any code was
written. Wording preserved; ellipses mark cuts.

---

**Agent (plan excerpt):**

> 2. README accuracy ... committed in ~10 meaningful git commits ...
> 3. Initial YC topic retrieval should be deterministic (BM25 + boosts +
>    recency) - NO LLM reranking initially ...
> Sourcing: ... BM25 → top 50 → LLM rerank optional → 10–12 YC ...
> Analysis: ... evidence-coverage penalty caps (`<0.40 → ≤69`, `<0.60 → ≤79`) ...
> fatal-risk override (evidence-backed `critical` risk downgrades
> TAKE_A_MEETING→WATCH, reason recorded)

**Me:**

> Pick OpenAI only for the take-home. Do not build two providers. Do not spend
> time on Anthropic fallback, provider abstraction, routing, retries across
> vendors ... That's exactly the kind of unnecessary architecture this
> assignment is warning against.
>
> One thing I would change immediately: do NOT promise ~10 commits upfront.
> This is slightly dangerous because their assignment explicitly warns against
> a trail assembled to look thorough. Do not manufacture commit history to
> satisfy a target count. Commit only at natural completed milestones. Maybe
> you naturally end up with 7 commits. Maybe 13. Doesn't matter. What matters
> is that they are real.
>
> Second change: don't pretend `v2` exists unless there is a real v2 ...
> Initially create `prompts/analysis_v1.md` only. Do not create an empty
> `analysis_v2.md`. If an actual failure happens ... Now Git itself proves
> when the change happened. Much stronger.
>
> Third change: I would simplify candidate sourcing slightly ... I would
> initially skip LLM reranking. Start with deterministic ranking ... Then see
> if the results suck. Only introduce LLM reranking if you find a real
> failure. That's another perfect AI-workflow story ... Much better than
> adding LLM because architecture says so.
>
> Fourth change: be careful with YC data source ... Use the mirror strictly as
> a discovery/indexing optimization. For evidence ... canonical evidence URL:
> https://www.ycombinator.com/companies/<slug>
>
> Fifth: Do not cap or mutate the raw investment score because evidence is
> sparse. Keep investment attractiveness and evidence confidence independent.
> Example: score = 86, evidence_confidence = LOW, recommendation = WATCH,
> override_reason = insufficient evidence for high-confidence meeting call
>
> Sixth: Avoid a generic model-controlled fatal-risk override unless clearly
> deterministic. Prefer recommendation gating for low evidence and expose
> critical risks separately.
>
> Seventh: For company-site enrichment, inspect internal links from the
> homepage and select up to 3 useful pages based on anchors/paths such as
> about, team, founders, company, customers, case-studies instead of blindly
> requesting fixed paths.
>
> Eighth: Keep discovery relevance score completely separate from investment
> score. Ninth: Add explicit scoring anchors/rubric bands for every scoring
> dimension to the thesis YAML ... Tenth: Add top-level unknowns[] to
> InvestmentAnalysis. Eleventh: When a claim originates from first-party
> marketing material, qualify it as "company-reported" unless independently
> corroborated. Twelfth: Record provider/model/prompt_version and, when
> available, token usage in run.json.

**Agent (revised plan):**

> 1. ✅ No commit-count targets — commit only at natural milestones
> 2. ✅ `prompts/analysis_v1.md` only; v2 created only if a real observed
>    failure demands it
> 3. ✅ Deterministic YC retrieval — no LLM reranking initially
> 4. ✅ yc-oss = discovery index only; all YC evidence cites canonical
>    `ycombinator.com/companies/<slug>` URLs
> 5. ✅ Score is never capped/mutated ... `score=86, evidence_confidence=LOW,
>    recommendation=WATCH, override_reason="insufficient evidence for
>    high-confidence meeting call"` as independent dimensions
> 6. ✅ No model-controlled fatal override — deterministic low-evidence gating
>    on TAKE_A_MEETING only; critical risks exposed in memo
> 7. ✅ Homepage link discovery → keyword-scored selection of ≤3 internal
>    pages, not blind fixed paths
> ... (12/12 applied)

---

**Outcome:** all twelve corrections shipped. The most visible in the final
artifacts: `scoring/recommendation.py` implements the deterministic evidence
gate instead of a score cap; critical risks surface in the memo's "What could
kill this" with no code path that lets the model change the call; and the
committed git history has no manufactured count.
