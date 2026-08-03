# CI Gating

Turn environment evidence into an explicit release decision. CI should parse
stable result data, print the reason for a decision, and leave the presentation
grid available for humans.

## Files

- `basic.py` — gate on aggregate pass rate and unscored attempts from `summary()`.
- `per_task_floor.py` — require every task to meet an individual reliability floor.
- `baseline_regression.py` — reject task-level drops beyond a configured tolerance.

## When to use

Use CI gates after local calibration has produced meaningful task rows. An
aggregate gate is compact but can hide one weak task; a per-task floor protects
critical cases; a baseline diff catches regressions without requiring perfection.
The baseline example compares `gpt-5.5` high reasoning with a low-reasoning
candidate through a policy-only model override.

The dataset workflow in
[`_27_verified_dataset/`](../_27_verified_dataset/) uses the same pass-rate
evidence for curation. Saved results and diffs are introduced in
[`_13_saved_baselines/`](../_13_saved_baselines/) and
[`_14_environment_diff/`](../_14_environment_diff/).

## Run

```bash
python cookbook/environments/_28_ci_gating/basic.py
python cookbook/environments/_28_ci_gating/per_task_floor.py
python cookbook/environments/_28_ci_gating/baseline_regression.py

# Production enforcement examples: FAIL exits with status 1.
python cookbook/environments/_28_ci_gating/basic.py --enforce
python cookbook/environments/_28_ci_gating/per_task_floor.py --enforce --minimum-task-rate 1.0
python cookbook/environments/_28_ci_gating/baseline_regression.py --enforce --maximum-drop 0.0
```

Requires `OPENAI_API_KEY`. The normal teaching commands exit successfully so
their live runs can be inspected. Every file accepts `--enforce`, which maps a
FAIL decision to exit status 1 for production CI. The configurable thresholds
are `--minimum-pass-rate`, `--minimum-task-rate`, and `--maximum-drop`.
