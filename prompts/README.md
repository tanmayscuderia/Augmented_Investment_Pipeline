# Prompt versions

Prompts are versioned as `analysis_v<N>.md`. The active version is selected with
`--prompt-version` (default `v1`) and recorded in every `run.json`.

- `analysis_v1.md` — initial evidence-constrained analyst prompt: citation
  requirements, company-reported qualifiers, UNKNOWN handling, anchor-based
  scoring, no invented market numbers.

A `v2` is created **only** when a real, observed model failure on a real run
demonstrates that v1 is insufficient. The failure and the fix are documented in
`process/AI_WORKLOG.md` and validated by an eval case in `evals/cases.yaml`.
