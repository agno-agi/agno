# Review Log: context_compression

> Updated: 2026-02-11

## Framework Issues

[FRAMEWORK] libs/agno/agno/team/team.py:492-493 — No validation when both `compress_tool_results=True` and `compression_manager` are provided simultaneously. If user sets both, `compression_manager` takes precedence silently.

[FRAMEWORK] libs/agno/agno/compression/manager.py:93+138 — Threshold semantics: `compress_tool_results_limit` keeps last N results uncompressed, but naming suggests it limits total compressed results. Confusing API.

[FRAMEWORK] libs/agno/agno/compression/manager.py:85+174 — No guard around potential model call failure during compression. If compression model call fails, the exception propagates and kills the entire team run.

## Cookbook Quality

[QUALITY] tool_call_compression.py — Uses mixed providers (AwsBedrock for sync, OpenAIChat for async) which makes testing harder and requires both AWS and OpenAI credentials. Would be clearer with a single provider.

[QUALITY] tool_call_compression.py — Doesn't show before/after comparison of compressed vs uncompressed context sizes, missing the main educational value.

[QUALITY] tool_call_compression_with_manager.py — Comment says "Keep only last 2 tool call results uncompressed" but parameter name `compress_tool_results_limit=2` reads ambiguously. Good example of custom compression prompt though.

## Fixes Applied

None — both cookbooks are compatible with v2.5 API as-is.
