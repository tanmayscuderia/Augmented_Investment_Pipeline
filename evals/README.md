# Evals

Six cases (five areas). Checks are deterministic code in
`../src/investment_pipeline/evals.py`; `cases.yaml` documents intent. Results
are committed in `results.json`.

## Run

```bash
uv run pipeline eval          # static cases only (offline)
uv run pipeline eval --live   # + LLM-backed cases (needs OPENAI_API_KEY)
```

## Cases

| Case | Mode | What it proves |
|---|---|---|
| `citation_integrity` | static | Every referenced evidence ID resolves in the bundle; a fabricated `E999` is flagged. |
| `factual_claim_without_citation` | static | A FACT claim (`inference=false`) with empty `evidence_ids` is rejected. |
| `thin_evidence` | static | Thin evidence cannot buy a high-conviction call: a 97/100 on 33% coverage stays score 97, confidence LOW, call WATCH with a recorded override. |
| `missing_founder_information` | live | With zero founder evidence, the model must emit no factual founder claims and must surface the gap in `unknowns[]`. In the committed run the model first tried an uncited founder claim; the validator rejected it; the retry corrected it. |
| `unsupported_market_size` | live | Any numeric market figure must be cited to evidence that actually contains it. |
| `obvious_ai_wrapper` | live | An obvious wrapper must raise a defensibility / model-dependency concern. |

## Current results

`results.json`: **6/6 pass** (3 static + 3 live, model `deepseek-v4-flash`).

Live cases exist because the two failure modes that matter for this assignment
— invented founder histories and invented market numbers — are exactly what a
citation-only validator cannot catch when the cited evidence genuinely exists
but does not support the claim.
