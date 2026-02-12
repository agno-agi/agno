# Review Log: structured_input_output

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

[FRAMEWORK] team/_init.py:191 — `mode` parameter accepted without validation/coercion. Invalid strings silently pass through instead of raising early.

[FRAMEWORK] team/_run.py:841,2238 — Task-mode streaming fallback yields a non-iterator (TeamRunOutput) where callers may expect Iterator. Could cause type errors if task_mode cookbooks try `stream=True`.

## Cookbook Quality

[QUALITY] input_formats.py — List-of-strings input format is accepted but not pedagogically clear; could confuse new users about when to use list vs string input.

[QUALITY] parser_model.py — Type annotation uses `RunOutput` for team run result; should be `TeamRunOutput` for correctness.

[QUALITY] response_as_variable.py — Runtime type asserts depend on response structure; fragile if model doesn't return expected schema.

[QUALITY] structured_output_streaming.py — Relies on "last streamed item" having the complete structured output; this is a valid pattern but could be documented better.

## Fixes Applied

None needed — all 10 files are LIKELY OK for v2.5.
