# REVIEW LOG

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Framework Issues

[FRAMEWORK] agno/agent/_hooks.py:67 — `debug_mode or agent.debug_mode` logic prevents explicitly forcing `debug_mode=False` when agent has `debug_mode=True`.

[FRAMEWORK] agno/agent/_hooks.py:72 — In "run all hooks in background" path, `kwargs` are never merged before dispatch to background tasks, potentially missing context parameters.

## Cookbook Quality

[QUALITY] session_state_hooks.py — Creates an Agent inside the hook on every run (expensive, defeats agent reuse principle). Should use module-level agent.

[QUALITY] stream_hook.py — Filename suggests stream-hook semantics, but is really a post-hook that happens to run after streaming. Name is slightly misleading.

[QUALITY] pre_hook_input.py — Powerful but costly pattern (LLM-in-hook per request). Should warn about latency implications.

[QUALITY] post_hook_output.py — `run_output.content.strip()` assumes content is always a string; could fail on None content.

## Fixes Applied

None — all cookbooks are v2.5 compatible as-is.
