# Saved Baselines

Persist rollout evidence as plain JSON so a later run can be compared with the
same task-level history and fingerprints. Saved artifacts include full prompts
and responses and should be handled as sensitive evaluation data.

## Files

- `basic.py` — run an environment and save its result as a baseline.
- `reload_baseline.py` — reload the artifact and verify its summary survived
  the round trip.
- `async_save_load.py` — use the async rollout, save, and load twins.

## When to use

Use this when the baseline and candidate cannot run in the same process, or
when CI needs a reviewed reference artifact. Continue to
[`_14_environment_diff/`](../_14_environment_diff/) to compare compatible
results task by task.

A baseline is evidence from a particular environment and policy, not a promise
that future tasks or prompt edits remain comparable.

## Run

```bash
python cookbook/environments/_13_saved_baselines/basic.py
python cookbook/environments/_13_saved_baselines/reload_baseline.py
python cookbook/environments/_13_saved_baselines/async_save_load.py
```

Requires `OPENAI_API_KEY`. Every example uses `gpt-5.5` through
`OpenAIResponses`.
