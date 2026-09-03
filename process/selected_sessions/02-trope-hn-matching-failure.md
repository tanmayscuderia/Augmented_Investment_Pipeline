# 02 — HN story matching failure (Trope, then Qlo/Balance/Raindrop)

**Date:** 2026-09-03 · **Agent:** Cline · **Trimmed excerpt of a real session.**
A live end-to-end smoke run produced polluted evidence; this excerpt covers the
detection, the diagnosis, the first fix, its recurrence under a race, and the
final hardening. Wording preserved; ellipses mark cuts.

---

**Me:** so what is now left to do and what is working or not

**Agent:** ... inspecting the evidence JSON:

> **A real failure just surfaced — and it's a good one:** Trope's HN
> enrichment matched the wrong stories. E003–E007 are about *narrative
> tropes* ("TropeTwist: Trope-Based Narrative Structure Generation", "The
> Soap Bubble Trope", "The Fanfic Sex Trope That Caught a Plundering AI
> Red-Handed"...) — the `_story_matches` name-substring rule matched any
> story with the word "trope" in the title! The company is "Trope"
> (trope.ai, AI FDE for ERPs), but the word "trope" is a common English
> noun, so title matching produced garbage evidence.
>
> **Fix:** require domain match OR (name match AND the story is Show HN) ...
> Regression test added ... Re-ran the pipeline: Trope's evidence went from
> 7 items (5 wrong) to 2 clean items.

*(The first fix shipped. The QLO-collision regression test came later; the
full sample run then launched ~60 seconds before that edit landed, so it ran
on the old matcher — discovered in the next review.)*

**Agent (audit of the committed run):**

> **The defect: 4 of 15 evidence bundles contain HN pollution**
>
> | Company | Junk items | What slipped in |
> | Balance | 5/5 HN items | work-life-balance apps, CalmJobs, WLBList |
> | Raindrop | 4/5 | raindrop.io (a *different company* — the bookmark app) |
> | Wedge | 2/2 | chart patterns, wedge-tail eagle |
> | Qlo | 1/1 | the 2020 clothing "QLO" |
>
> **Root cause:** the final run launched ~60 seconds *before* my matcher fix
> landed ... Worse — my fix was itself **insufficient**: for common-word
> names, "Show HN: CalmJobs – … work-life balance" still matches (any Show HN
> whose title merely *mentions* the name).
>
> Notably, the model itself refused to cite the junk: Wedge's memo says "The
> Hacker News posts are unrelated to the company" — the constraints held even
> when the collector failed.

**Fix #3 (final rule):**

> Strengthen the name-only rule with a **links-home test**: a name-only match
> is accepted only if the story links to *no* URL or to the company's own
> domain (a story linking to `raindrop.io` is by definition about another
> company), plus strict launch-shape (`^(Show HN: )?<name>`), keeping len≥4 +
> 3-year recency.

**Verification after re-running research (all fetches served from cache):**

> Wedge, Qlo, and Balance are pollution-free (Balance and Qlo now have zero
> HN items — correctly, since nothing on HN is actually about them) ... the
> remaining HN evidence is all genuinely on-topic ... citation sweep: 15/15
> fully valid.

---

**Why this mattered:** the citation validator could never have caught this
class of failure — every polluted citation *resolved* to real evidence; the
evidence was simply irrelevant. Retrieval relevance had to be fixed at
collection time, with regression tests pinning each real case (Trope, QLO,
Raindrop.io).
