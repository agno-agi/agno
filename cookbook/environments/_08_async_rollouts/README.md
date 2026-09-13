# Async Rollouts

Run independent attempts concurrently from an async application. The result
shape is the same as the synchronous runner, including the grid, pass rates,
fingerprints, and learning-zone selection.

## Files

- `basic.py` — await `arun_rollouts()` with bounded concurrency.
- `async_export.py` — run asynchronously, then export passing middle-band traces.

## When to use

Use async rollouts in services, notebooks with an async entry point, or batch
jobs where model latency dominates. Concurrency changes wall-clock time, not the
meaning or ordering of the recorded attempts.

Calibrate the tasks first with
[`_07_difficulty_calibration/`](../_07_difficulty_calibration/). Next,
[`_09_task_selection/`](../_09_task_selection/) runs only a chosen subset.

## Run

```bash
python cookbook/environments/_08_async_rollouts/basic.py
python cookbook/environments/_08_async_rollouts/async_export.py
```

Requires `OPENAI_API_KEY`. Export writes a dataset; it does not train a model.
