# Review Log: guardrails

> Updated: 2026-02-11

## Framework Issues

[FRAMEWORK] libs/agno/agno/team/_run.py:723 — `InputCheckError` is caught internally by `team.run()` and converted to a `RunOutput` with error content. It is NOT re-raised to the caller. This means `try/except InputCheckError` around `print_response()`/`aprint_response()` in the cookbooks is dead code — the exception never reaches it. The error still displays correctly because `print_response` renders the error `RunOutput`.

[FRAMEWORK] libs/agno/agno/team/_run.py:1288-1293 vs 2732-2737 — Hook normalization is cached via `_hooks_normalised` flag. The first call (sync or async) determines the hook mode for all subsequent calls. If a team is used in both sync and async modes, hooks normalized for one mode may behave unexpectedly in the other.

## Cookbook Quality

[QUALITY] All 3 guardrails cookbooks use `members=[]` (empty member list), making the team behave like a single agent with guardrails. This doesn't demonstrate team-specific guardrail behavior (e.g., guardrails applied to member inputs/outputs vs team-level I/O).

[QUALITY] prompt_injection.py prints `[WARNING] This should have been blocked!` after every blocked response, which is confusing — the test DID block the input. The warning message is misleading.

[QUALITY] openai_moderation.py uses `aprint_response` (async) while the others use sync `print_response`. Mixing async/sync across the same cookbook category reduces consistency.

## Fixes Applied

None — all cookbooks are compatible with v2.5 API as-is.
