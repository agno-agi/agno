# REVIEW LOG — dependencies

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Summary

3 files reviewed. No blocking fixes. 1 minor deprecation warning.

## dependencies_in_context.py

- **[FRAMEWORK]** `dependencies={str: callable}` and `add_dependencies_to_context=True` are valid Agent params (`agent.py:373`). Callables resolved at runtime via `_run.py:117`.
- **[QUALITY]** Good real-world example with live HackerNews API. Minor: httpx calls lack timeout/retry/error handling.
- **[COMPAT]** No deprecated imports.

## dependencies_in_tools.py

- **[FRAMEWORK]** Tool with `run_context: RunContext` parameter correctly receives injected dependencies. `run_context.dependencies` field exists (`run/base.py:24`).
- **[QUALITY]** Strong example showing dependency injection into tools. Clear print statements for debugging.
- **[COMPAT]** No issues.

## dynamic_tools.py

- **[FRAMEWORK]** `tools=get_runtime_tools` callable factory with RunContext is correct. Same pattern as callable_factories cookbooks.
- **[QUALITY]** Minor: `datetime.utcnow()` is deprecated in Python 3.12+. Should use `datetime.now(datetime.UTC)`.
- **[COMPAT]** OpenAIResponses(gpt-5.2) consistent with codebase.

## Framework Files Checked

- `libs/agno/agno/agent/agent.py:373` — dependencies, add_dependencies_to_context
- `libs/agno/agno/agent/_run.py:117` — dependency resolution at runtime
- `libs/agno/agno/run/base.py:24` — RunContext.dependencies field
- `libs/agno/agno/utils/callables.py:60-130` — callable factory invocation
