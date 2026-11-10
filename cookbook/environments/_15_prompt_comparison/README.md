# Prompt Comparison

Compare pass-rate summaries before and after an instruction edit. Prompts are
part of the environment, so these runs have different environment fingerprints
and cannot be passed to `EnvironmentDiff`.

## Files

- `basic.py` — place two prompt summaries side by side.
- `instruction_detail.py` — compare terse and step-checking instructions and
  demonstrate the fingerprint guard.
- `format_constraint.py` — compare concise and explanation-bearing response
  instructions under the same typed answer schema.

## When to use

Use this for experiments where the prompt itself is the independent variable.
Treat the result as two separate environment measurements, not as a policy-only
diff. For a valid `EnvironmentDiff`, use
[`_14_environment_diff/`](../_14_environment_diff/); for model request settings,
continue to [`_16_policy_settings/`](../_16_policy_settings/).

## Run

```bash
python cookbook/environments/_15_prompt_comparison/basic.py
python cookbook/environments/_15_prompt_comparison/instruction_detail.py
python cookbook/environments/_15_prompt_comparison/format_constraint.py
```

Requires `OPENAI_API_KEY`. Every example uses `gpt-5.5` through
`OpenAIResponses`.
