# Quality Review

Multi-agent quality control on top of any extraction primitive: two
labelers (different providers) extract independently, a reviewer
identifies disagreement, an adjudicator resolves it against the original
input. Use this when label quality matters more than throughput.

## Files

- `basic.py` — labeler → reviewer → adjudicator applied to text
  extraction (the `_03_text_extraction/basic.py` Contact schema). The same
  pattern composes on top of any image / audio / document extraction
  cookbook in this directory.

## When to use

- High-value labels where a wrong answer is expensive.
- Building eval / training sets where disagreement is itself signal.
- Regulated workloads where you need an auditable resolution trail.

If you only need single-pass extraction, use the relevant `*_extraction/`
cookbook. If you need provider ensembling for evals rather than labels,
see [`_17_llm_as_judge/`](../_17_llm_as_judge/).

## Composition

`basic.py` is a flat imperative pipeline (three sequential agent calls).
For production traceability and parallelism, wrap the same agents in
`Workflow(Parallel(labeler_a, labeler_b), reviewer, Condition(adjudicator))` -
see `cookbook/04_workflows/04_parallel_execution/parallel_with_condition.py`.

## Run

```bash
python cookbook/data_labeling/_18_quality_review/basic.py
```

Requires `GOOGLE_API_KEY` and `ANTHROPIC_API_KEY` (the two labelers run
on different providers for ensemble diversity).
