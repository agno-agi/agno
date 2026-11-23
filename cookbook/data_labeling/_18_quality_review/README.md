# Quality Review

Multi-agent quality control on top of any extraction primitive: two
labelers (different providers) extract independently, a reviewer
identifies disagreement, an adjudicator resolves it against the original
input. Use this when label quality matters more than throughput.

## Files

- `basic.py` — labeler → reviewer → adjudicator expressed as an agno
  Workflow: the two labelers run inside `Parallel(...)`, the reviewer
  diffs their outputs field by field, and a `Condition` step runs the
  adjudicator only when the reviewer flags disagreement. Applied to text
  extraction (the `_03_text_extraction/basic.py` Contact schema); the
  same shape composes on top of any image / audio / document extraction
  cookbook in this directory.

The demo runs two inputs — a clean one where the labelers agree and the
adjudication step is skipped, and one with deliberately conflicting
details where the adjudicator resolves the disagreement — and prints the
full step trail for both.

## When to use

- High-value labels where a wrong answer is expensive.
- Building eval / training sets where disagreement is itself signal.
- Regulated workloads where you need an auditable resolution trail.

If you only need single-pass extraction, use the relevant `*_extraction/`
cookbook. If you need provider ensembling for evals rather than labels,
see [`_17_llm_as_judge/`](../_17_llm_as_judge/).

## Composition

The workflow is `Parallel(labeler_a, labeler_b)` → reviewer →
`Condition(adjudicator)`, with every run persisted to SQLite
(`tmp/labeling.db`) for traceability. Swap the labeler agents and the
schema to apply the same quality gate to any other primitive in this
directory.

## Run

```bash
python cookbook/data_labeling/_18_quality_review/basic.py
```

Requires `GOOGLE_API_KEY` and `ANTHROPIC_API_KEY` (the two labelers run
on different providers for ensemble diversity).
