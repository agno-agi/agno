# Review Log: 01_quickstart

> Updated: 2026-02-11 (empirical verification pass)

## Framework Bugs (Source-Verified)

### BUG-1: Broadcast async gather missing `return_exceptions=True`

**Location:** `libs/agno/agno/team/_default_tools.py:1080`
**Verdict:** REAL BUG
**Severity:** Crash — single member failure kills entire broadcast

**Code:**
```python
# Line 1080 — CURRENT (buggy)
results = await asyncio.gather(*[task() for task in tasks])

# Compare to _run.py:3510 — CORRECT
results = await asyncio.gather(*tasks, return_exceptions=True)
```

**Why it's real:** The inner `run_member_agent` closure (lines 989-1076) has a `try/except` at line 1043, but it only wraps the content formatting logic (lines 1043-1074). The `arun()` call (line 997), `check_if_run_cancelled()` (line 1018), and `_process_delegate_task_to_member()` (lines 1036-1041) are all OUTSIDE any try/except. If any of these raise (model API error, cancelled run, malformed response), the exception propagates to `asyncio.gather`, which without `return_exceptions=True` cancels all other pending member tasks.

**Empirical proof:** Test script shows `asyncio.gather` without `return_exceptions=True` cancels `slow_member` when `failing_member` raises. With `return_exceptions=True`, both complete independently.

**Correct pattern exists at:** `_run.py:3510` (team parallel execution), `_task_tools.py:802` (task mode parallel execution).

---

### BUG-2: Post-hook error preserves rejected content

**Location:** `libs/agno/agno/team/_run.py:736` (sync non-stream), also at `:1156` (sync stream), `:2039` (async non-stream)
**Verdict:** REAL BUG
**Severity:** Silent data loss / security bypass for output guardrails

**Code:**
```python
# Line 723-743
except (InputCheckError, OutputCheckError) as e:
    run_response.status = RunStatus.error
    run_error = create_team_run_error_event(...)
    run_response.events = add_team_error_event(...)
    if run_response.content is None:   # <-- Only sets if None!
        run_response.content = str(e)
```

**Why it's real:**
- Pre-hook `InputCheckError` → `content` is None → error message IS set in content
- Post-hook `OutputCheckError` → `content` has model output → error message is LOST, rejected content preserved
- `print_response()` at `utils/print_response/team.py` does NOT check `RunStatus.error` — it renders whatever is in `content`
- For security guardrails (PII detection, prompt injection blocking), the blocked content IS returned to the caller

**Empirical proof:** Simulation shows post-hook scenario returns `content="Here is the user's SSN: 123-45-6789"` with `status=error` — the PII-containing response is returned despite the guardrail blocking it.

**Practical impact:** Any code that reads `run_response.content` without checking `run_response.status` gets the guardrail-rejected content. This includes `print_response()`, the most common consumer.

---

### BUG-3: Missing error event in `acontinue_run`

**Location:** `libs/agno/agno/team/_run.py:4600-4608`
**Verdict:** REAL BUG
**Severity:** Degraded behavior — guardrail failures invisible to event consumers

**Code:**
```python
# Line 4600-4608 — acontinue_run (MISSING error event)
except (InputCheckError, OutputCheckError) as e:
    run_response.status = RunStatus.error
    if run_response.content is None:
        run_response.content = str(e)
    log_error(...)
    # NO create_team_run_error_event()!
    # NO add_team_error_event()!
```

**Compare to line 2029-2038 (arun — correct):**
```python
except (InputCheckError, OutputCheckError) as e:
    run_response.status = RunStatus.error
    run_error = create_team_run_error_event(
        run_response, error=str(e), error_id=e.error_id,
        error_type=e.type, additional_data=e.additional_data,
    )
    run_response.events = add_team_error_event(...)
```

**Why it's real:** The generic `Exception` handler at the same scope (lines 4627-4629) DOES create error events, making this an obvious copy-paste omission. Event consumers processing `run_response.events` to detect guardrail failures will see nothing — the error only shows in logs.

**Empirical proof:** Side-by-side comparison shows `arun` error events list has the event, `acontinue_run` error events list is empty, while `acontinue_run` generic exception events list has the event.

---

### BUG-4: Sync dependency resolver stores coroutine objects

**Location:** `libs/agno/agno/team/_run.py:2994-3023` (sync) vs `:3026-3058` (async)
**Verdict:** REAL BUG (edge case)
**Severity:** Degraded behavior — silent wrong type, ResourceWarning for unawaited coroutine

**Code:**
```python
# Sync resolver (line 3019) — MISSING iscoroutine check
resolved_value = value(**kwargs) if kwargs else value()
run_context.dependencies[key] = resolved_value

# Async resolver (line 3051-3054) — CORRECT
resolved_value = value(**kwargs) if kwargs else value()
if iscoroutine(resolved_value):
    resolved_value = await resolved_value
run_context.dependencies[key] = resolved_value
```

**Why it's real:** When an async callable is passed as a dependency factory and `team.run()` (sync) is called, the resolver calls the async function, gets a coroutine object, and stores it. No error. No warning. Downstream code gets `<coroutine object>` instead of the resolved value. Python will emit `RuntimeWarning: coroutine was never awaited`.

**Empirical proof:** Test script calls `async_db_factory()` without await, confirms result is `<class 'coroutine'>` instead of `<class 'dict'>`. Async resolver with `iscoroutine()` check correctly resolves to the dict.

**Practical impact:** LOW — users who define async factory functions almost certainly call `team.arun()`, not `team.run()`. The sync/async mismatch is unusual. However, the fix is trivial: add `iscoroutinefunction(value)` check to the sync resolver and either raise an error or use `asyncio.run()` to resolve.

---

## Framework Issues (Non-Bug)

[FRAMEWORK] libs/agno/agno/team/team.py:390 — Hook normalization is one-time per Team instance via `_hooks_normalised` flag. First sync or async call determines the normalization mode for all subsequent calls. Not a crash bug but creates cross-mode mismatch potential when the same Team instance is used in both sync and async paths.

[FRAMEWORK] libs/agno/agno/team/_default_tools.py:575,714 — `respond_directly=True` has no fallback if chosen member fails or returns empty content. The delegate tool yields an empty string, which produces a blank response. Consider adding retry or error propagation.

---

## Fixes Verified

[FIXED] libs/agno/agno/db/sqlite/sqlite.py:998 — The `NameError: name 'requirements' is not defined` bug reported in prior test runs (2026-02-08) has been **fixed** in v2.5. Line 998 is now `team_data=serialized_session.get("team_data")`.

---

## Cookbook Quality

[QUALITY] 01_basic_coordination.py — Uses Newspaper4kTools which fetches external URLs (zhipu.ai has expired SSL cert, github.com returns 404). These external dependencies make the cookbook unreliable. Consider using a more stable URL source or mocking the tool.

[QUALITY] broadcast_mode.py (~112s) and task_mode.py (~144s) exceed the standard 120s timeout. Both require 180s+ timeout to complete. Consider reducing task complexity or member count.

[QUALITY] nested_teams.py — Prior run (2026-02-08) timed out but current run (2026-02-11) completed. This is a non-deterministic timeout depending on model response speed.

[QUALITY] Files 04-07 all use SqliteDb with tmp/ directory paths. Good for demos but the session files accumulate across runs without cleanup.

---

## Fixes Applied

None — all cookbooks are compatible with v2.5 API as-is.
