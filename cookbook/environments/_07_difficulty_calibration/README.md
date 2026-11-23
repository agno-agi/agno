# Difficulty Calibration

Tune task difficulty until repeated attempts expose the model's boundary. Add
steps, larger operands, or controlled ambiguity gradually; do not accept an
all-full grid as evidence that a benchmark is useful.

## Files

- `basic.py` — build an easy-to-edge difficulty ladder.
- `chained_arithmetic.py` — add independently checkable arithmetic stages.
- `ambiguity_ladder.py` — increase uncertainty through natural-language scope.

## When to use

Use calibration before publishing a benchmark or exporting its passing traces.
Anchors confirm basic competence, while the middle band shows where attempts
still disagree. Tasks with zero passes may need decomposition instead of more
samples.

This operationalizes the learning-zone selection in
[`_06_learning_zone/`](../_06_learning_zone/). Once the task set has a useful
spread, [`_08_async_rollouts/`](../_08_async_rollouts/) runs it concurrently.

## Run

```bash
python cookbook/environments/_07_difficulty_calibration/basic.py
python cookbook/environments/_07_difficulty_calibration/chained_arithmetic.py
python cookbook/environments/_07_difficulty_calibration/ambiguity_ladder.py
```

Requires `OPENAI_API_KEY`. Calibrate against observed grids, not task labels
such as "easy" or "hard".
