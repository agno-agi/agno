# Environment Diff

Compare pass rates task by task when two results share the same environment
fingerprint. A model-policy change is comparable; a task, scorer, tool, or
prompt change is not.

## Files

- `basic.py` — compare low- and high-reasoning policies on one environment.
- `task_subset.py` — diff a selected task subset without hiding unmatched rows.
- `mismatch_guard.py` — show the exception raised when the environment changed.

## When to use

Use this after [`_13_saved_baselines/`](../_13_saved_baselines/) to turn a
candidate run into per-task deltas. Use
[`_15_prompt_comparison/`](../_15_prompt_comparison/) for prompt edits: prompt
changes alter the environment fingerprint and therefore cannot use
`EnvironmentDiff`.

Both comparable policies here are `gpt-5.5`; only the reasoning effort changes.

## Run

```bash
python cookbook/environments/_14_environment_diff/basic.py
python cookbook/environments/_14_environment_diff/task_subset.py
python cookbook/environments/_14_environment_diff/mismatch_guard.py
```

Requires `OPENAI_API_KEY`.
