# Error Analysis

Separate wrong answers from attempts that could not be scored. A pass-rate denominator
contains completed, scored attempts only; provider failures, timeouts, pauses, and
scorer exceptions remain visible as unscored evidence.

## Files

- `basic.py` — run a difficult task beside a deliberately unscorable row, then inspect
  `errors()` and the scored/unscored totals.
- `scorer_errors.py` — show that a verifier exception is captured per attempt instead
  of aborting the batch.
- `stop_reasons.py` — count the public `StopReason` values retained on every
  `AttemptResult`.

## When to use

Use these patterns when a low pass rate might really be an infrastructure problem, or
when a custom scorer is still being hardened. Inspect errors before using the reports
in [`_20_report_drilldown/`](../_20_report_drilldown/) or exporting any dataset.

## Run

```bash
.venvs/demo/bin/python cookbook/environments/_19_error_analysis/basic.py
.venvs/demo/bin/python cookbook/environments/_19_error_analysis/scorer_errors.py
.venvs/demo/bin/python cookbook/environments/_19_error_analysis/stop_reasons.py
```

Requires `OPENAI_API_KEY`. The scorer errors in these examples are deliberate and
local; they do not manufacture provider failures.
