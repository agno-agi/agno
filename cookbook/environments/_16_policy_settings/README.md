# Policy Settings

Compare request-shaping settings on the same `gpt-5.5` environment. A model
override changes the policy fingerprint while preserving the environment
fingerprint, making `EnvironmentDiff` valid.

## Files

- `basic.py` — override the environment's low-reasoning policy with high
  reasoning effort and diff the results.
- `reasoning_effort.py` — inspect the fingerprint split and task-level deltas
  for the two supported effort settings used here.

## When to use

Use this after [`_15_prompt_comparison/`](../_15_prompt_comparison/) when the
tasks, scorer, tools, and prompts stay fixed and only the model request policy
changes. A prompt-bearing model override is still an environment change.

The examples compare `gpt-5.5` low versus high reasoning effort; they do not use
a different model family.

## Run

```bash
python cookbook/environments/_16_policy_settings/basic.py
python cookbook/environments/_16_policy_settings/reasoning_effort.py
```

Requires `OPENAI_API_KEY`.
