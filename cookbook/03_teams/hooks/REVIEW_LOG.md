# Review Log: hooks

> Updated: 2026-02-11

## Framework Issues

[FRAMEWORK] libs/agno/agno/team/team.py:390 — `_hooks_normalised` flag is set once per team instance. First sync or async call normalizes hooks for that mode. If a team is used in both sync and async paths, the hooks normalized for one mode persist for the other, potentially causing `iscoroutinefunction()` mismatches at `_hooks.py:371`.

[FRAMEWORK] libs/agno/agno/team/_run.py:723 — `OutputCheckError` from post-hooks is caught internally by `team.run()` and returned as error `RunOutput`. The `try/except OutputCheckError` in `post_hook_output.py` around `aprint_response` is dead code — the exception never propagates to the caller.

[FRAMEWORK] libs/agno/agno/utils/hooks.py — `normalize_pre_hooks()` and `normalize_post_hooks()` convert callables to `HookWrapper` at team init time. They inspect function signatures to determine which kwargs to pass (`run_input`, `team`, `session`, `user_id`, etc.). This inspection uses `inspect.signature` which doesn't account for decorated functions that alter signatures.

## Cookbook Quality

[QUALITY] pre_hook_input.py — Creating Agent instances inside pre-hooks (lines 39-56, 116-130) causes nested LLM calls per invocation. This is an anti-pattern for hooks (which should be fast). The cookbook demonstrates a valid use case but is structurally too slow to run as a demo (~180s+ for 5 test cases). Consider reducing to 2 test cases or using a faster model.

[QUALITY] post_hook_output.py — Excellent coverage of 6 different post-hook patterns. Good mix of simple (metadata injection) and complex (inner Agent formatting) hooks. The `try/except OutputCheckError` blocks are misleading (see framework issue above).

[QUALITY] stream_hook.py — Clean, minimal example of `RunContext.metadata` usage in post-hooks. Uses `members=[]` which makes it agent-style rather than team-specific.

## Fixes Applied

None — all cookbooks are compatible with v2.5 API as-is.
