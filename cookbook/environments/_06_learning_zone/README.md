# Learning Zone

Find tasks whose repeated attempts include both passes and failures. For a
binary scorer, the learning zone is exactly `0 < pass_rate < 1`: neither already
mastered nor consistently failed.

## Files

- `basic.py` — run a mixed task set and call `learning_zone()`.
- `select_middle_band.py` — make the strict partial-pass-rate filter explicit.
- `saturated_tasks.py` — contrast saturated tasks with useful middle-band tasks.

## When to use

Use the learning zone to decide where more examples, prompt work, or verified
dataset curation can add signal. Full-pass tasks add repetition but little new
information; zero-pass tasks may be beyond the current policy.

This builds on the scorers in [`_03_code_scorer/`](../_03_code_scorer/),
[`_04_judge_scorer/`](../_04_judge_scorer/), and
[`_05_tool_call_scorer/`](../_05_tool_call_scorer/). Next,
[`_07_difficulty_calibration/`](../_07_difficulty_calibration/) shows how to
move a task into this band.

## Run

```bash
python cookbook/environments/_06_learning_zone/basic.py
python cookbook/environments/_06_learning_zone/select_middle_band.py
python cookbook/environments/_06_learning_zone/saturated_tasks.py
```

Requires `OPENAI_API_KEY`. This is repeated verification and task selection,
not a live RL reward loop.
