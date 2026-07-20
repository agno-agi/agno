# Task Sets

Collect repeatable inputs, expected values, ids, and metadata into the task
set an environment verifies. Task ids label the grid and align later diffs.

## Files

- `basic.py` — declares a small tuple of tasks with stable ids.
- `from_jsonl.py` — loads the same shape from checked-in JSONL.
- `with_metadata.py` — selects calibration rows by task metadata.
- `data/chained_arithmetic.jsonl` — local, reviewable task fixture.

## When to use

Use inline `Task` objects for a compact example and JSONL when a task set is
owned and reviewed as data. Metadata is useful for splits and difficulty
slices; it is not added to the prompt automatically.

Start with [`_01_first_environment/`](../_01_first_environment/) for the
minimal runner. Continue to [`_03_code_scorer/`](../_03_code_scorer/) to choose
how those task expectations become scores.

## Run

```bash
python cookbook/environments/_02_task_sets/basic.py
python cookbook/environments/_02_task_sets/from_jsonl.py
python cookbook/environments/_02_task_sets/with_metadata.py
```

Requires `OPENAI_API_KEY`. Every model call uses `OpenAIResponses` with
`gpt-5.5`.
