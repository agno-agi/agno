# Multi-step Tools

Verify workflows that need several read-only tool executions rather than one
lookup. The examples progress from required tool names to exact arguments and
finally an ordered dependency chain.

## Files

- `basic.py` — require both plan and hub-window lookups.
- `exact_arguments.py` — verify the exact record arguments used at both steps.
- `call_sequence.py` — score dependency order and the checksum-selected records
  together with a `CodeScorer`.

## When to use

Use multi-step verification when a plausible final answer can hide a skipped,
misrouted, or prematurely executed lookup. Name checks answer whether every
step ran; argument checks answer whether it ran against the right records; a
sequence check protects dependencies between steps.

This follows the domain tasks in
[`_25_support_triage/`](../_25_support_triage/). Tool-bearing attempts are not
portable text-only SFT examples, so the verified dataset in
[`_27_verified_dataset/`](../_27_verified_dataset/) uses tool-free tasks.

## Run

```bash
python cookbook/environments/_26_multi_step_tools/basic.py
python cookbook/environments/_26_multi_step_tools/exact_arguments.py
python cookbook/environments/_26_multi_step_tools/call_sequence.py
```

Requires `OPENAI_API_KEY`. All tools are read-only. Score executions, not a
model's claim that it used a tool.
