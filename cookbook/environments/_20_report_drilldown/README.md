# Report Drilldown

Move from a pass-rate row to the evidence underneath it. Reports show verdicts,
errors, tool executions, answers, and token usage; a single-attempt view renders the
full retained transcript.

## Files

- `basic.py` — print the default investigation report after a mixed rollout grid.
- `failed_only.py` — cap the failed-only report while preserving the count of hidden
  attempts.
- `single_attempt.py` — locate one failed attempt and print its complete evidence.

## When to use

Use the grid and `summary()` for orientation, then drill down before changing a prompt
or verifier. If the problem is missing scores rather than wrong answers, start with
[`_19_error_analysis/`](../_19_error_analysis/). The next folders apply this evidence
workflow to real task domains, beginning with [`_21_math/`](../_21_math/).

## Run

```bash
.venvs/demo/bin/python cookbook/environments/_20_report_drilldown/basic.py
.venvs/demo/bin/python cookbook/environments/_20_report_drilldown/failed_only.py
.venvs/demo/bin/python cookbook/environments/_20_report_drilldown/single_attempt.py
```

Requires `OPENAI_API_KEY`.
