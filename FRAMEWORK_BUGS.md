# Framework Bug Tracker

Bugs found during v2.5 cookbook testing & code audit.
Source-verified against `cookbooks/v2.5-testing` branch (2026-02-11).
Round 2 audit (2026-02-12): hooks/guardrails, knowledge, tools, agent/team modules.
Round 3 audit (2026-02-13): knowledge instance isolation (PR #6482 review).
Round 4 audit (2026-02-13): memory, vectordb/mongodb, workflow, API modules.
Round 9 audit (2026-02-13): AgentOS, agent/_run.py, team/_run.py, approval, eval, tracing.

---

## Confirmed Bugs

### BUG-001: File type systematically broken across workflow module

**Severity:** HIGH — silent data loss at every pipeline stage
**Location:** Multiple files (see below)
**Since:** v2.0.0 (2025-09-09, commit `934208671`)
**Status:** Open

**Description:**
The `File` media type was incompletely integrated into the workflow module. While `images`, `videos`, and `audio` are handled correctly at every stage, `files` was missed at 4 separate levels — a pervasive copy-paste omission.

**Affected locations (4 levels of data loss):**

1. **Step → StepOutput** (`step.py:1514-1534`): `_process_step_output` extracts `images`, `videos`, `audio` from Agent/Team responses but NOT `files`. Files produced by agents/teams are dropped before they even reach StepOutput.

2. **Container step chaining** (4 files): `_update_step_input_from_outputs` propagates `images`/`videos`/`audio` between sub-steps but NOT `files`:
   - `condition.py:206-236`
   - `loop.py:253-284`
   - `router.py:203-231`
   - `steps.py:126-156`

3. **WorkflowRunOutput** (`run/workflow.py:492`): The dataclass has `images`, `videos`, `audio` fields but NO `files` field.

4. **Workflow execution** (`workflow.py`): `output_files` is accumulated from each step in all 4 paths but never assigned to the response:
   - Sync (~line 1780): images/videos/audio assigned, files not
   - Stream (~line 2024): same
   - Async (~line 2364): same
   - Async-Stream (~line 2626): same

**The only correct handling:** `_create_step_input` (workflow.py:1550) passes `shared_files` to `StepInput`. But this data is lost once execution enters any container.

**Additional gap (from Codex re-validation):** `parallel.py:192` onward also omits files in result aggregation.

**Type field audit (2026-02-12):**
The `files` field exists correctly on all intermediate types:
- `RunOutput` (agent.py:615) — `files: Optional[List[File]] = None` ✓
- `TeamRunOutput` (team.py:609) — `files: Optional[List[File]] = None` ✓
- `StepInput` (types.py:28-31) — has `files` + serialization in `to_dict()`/`from_dict()` ✓
- `StepOutput` (types.py:82-85) — has `files` + serialization ✓
- `WorkflowRunOutput` (run/workflow.py:509-511) — **MISSING** `files` field ✗

The types are wired correctly — the bug is purely in the workflow glue code (extraction, propagation, assignment) and the missing field on WorkflowRunOutput.

**Fix required (4 parts):**
1. Add `files = getattr(response, "files", None)` and `files=files` to `_process_step_output` in `step.py`
2. Add `current_files` / `all_files` / `files=` to `_update_step_input_from_outputs` in all 4 containers
3. Add `files: Optional[List[File]] = None` to `WorkflowRunOutput` in `run/workflow.py`
4. Add `workflow_run_response.files = output_files` after the audio assignment in all 4 execution paths

**Verification:**
Any workflow with steps that produce `File` objects — files are silently dropped at every stage.

---

### BUG-002: Parallel crashes with zero steps (sync paths only)

**Severity:** LOW — edge case, no real-world impact
**Location:** `libs/agno/agno/workflow/parallel.py:339, :513`
**Since:** v2.0.0
**Status:** Open

**Description:**
`ThreadPoolExecutor(max_workers=len(self.steps))` raises `ValueError: max_workers must be greater than 0` when `self.steps` is empty. No guard in `__init__`, `_prepare_steps`, or the workflow engine.

Only sync paths crash (lines 339, 513). Async paths use `asyncio.gather(*[])` which returns `[]` safely.

**Practical impact:** None. All 100+ usages across cookbooks and tests pass at least 1 step. The only zero-step test (`test_per_request_isolation.py:952`) tests serialization, not execution.

**Fix:** One-liner early return in `execute` and `execute_stream`:
```python
if not self.steps:
    return StepOutput(step_name=self.name, content="No steps to execute")
```

---

### BUG-003: Step silently dropped when add_workflow_history=True and no DB

**Severity:** MEDIUM — silent behavior change
**Location:** `libs/agno/agno/workflow/workflow.py:4273-4278`
**Since:** v2.5.0 (when `add_workflow_history` was added)
**Status:** Open

**Description:**
In `_prepare_steps`, when a `Step` has `add_workflow_history=True` but the `Workflow` has no database configured, the step is matched by the `elif` branch at line 4273 which logs a warning but does NOT append the step to `prepared_steps`. The step is silently removed from the workflow.

The `elif` chain:
```python
elif isinstance(step, Step) and step.add_workflow_history is True and self.db is None:
    log_warning(...)          # warns, but...
    # NO prepared_steps.append(step)  ← step is dropped!
elif isinstance(step, (Step, Steps, ...)):
    prepared_steps.append(step)  # never reached for this step
```

**Impact:** Any workflow that uses `Step(add_workflow_history=True)` without configuring a database will silently skip that step entirely. The warning message says "History won't be persisted" but the actual behavior is "Step won't execute."

**Fix:** Add `prepared_steps.append(step)` after the warning:
```python
elif isinstance(step, Step) and step.add_workflow_history is True and self.db is None:
    log_warning(...)
    prepared_steps.append(step)  # Still execute the step
```

**Impact analysis (2026-02-12):**
- No open PRs or issues address this bug (searched `gh pr list` and `gh issue list`)
- PR #5288 (`fix-wf-agent-history`) touches `step.py` but NOT `_prepare_steps` — different bug
- No existing cookbooks are affected: all 7 cookbooks using `add_workflow_history` also configure a DB:
  - `intent_routing_with_history.py` — SqliteDb ✓
  - `step_history.py` — SqliteDb ✓
  - `history_in_function.py` — SqliteDb ✓
  - `continuous_execution.py` — SqliteDb ✓
  - `workflow_with_history.py` — SqliteDb ✓
  - `basic.py` (agent_os) — SqliteDb ✓
- Bug only triggers when `add_workflow_history=True` AND `db=None`

---

### BUG-004: Image artifact UTF-8 decode fails on raw PNG bytes

**Severity:** MEDIUM — silent image data loss
**Location:** `libs/agno/agno/workflow/step.py:1585-1606`
**Since:** v2.5.0
**Status:** Open

**Description:**
`_convert_image_artifacts_to_images` assumes all `bytes` content in `ImageArtifact` is base64-encoded text. When the content is raw image bytes (e.g., PNG starting with `\\x89PNG`), the `decode("utf-8")` at line 1587 throws `UnicodeDecodeError`. The exception is caught at line 1603, and the image is silently skipped.

```python
if isinstance(img_artifact.content, bytes):
    base64_str: str = img_artifact.content.decode("utf-8")  # ← fails on raw PNG
    actual_image_bytes = base64.b64decode(base64_str)
else:
    actual_image_bytes = img_artifact.content
```

**Observed in:** `selector_media_pipeline.py` async path — `'utf-8' codec can't decode byte 0x89 in position 0` (PNG header). Sync path succeeded (likely because the model returned a URL instead of raw bytes).

**Fix:** Add fallback for raw image bytes:
```python
if isinstance(img_artifact.content, bytes):
    try:
        base64_str = img_artifact.content.decode("utf-8")
        actual_image_bytes = base64.b64decode(base64_str)
    except (UnicodeDecodeError, binascii.Error):
        actual_image_bytes = img_artifact.content  # Raw image bytes
else:
    actual_image_bytes = img_artifact.content
```

---

### BUG-005: Knowledge URL validation missing `return` after failure

**Severity:** HIGH — crash + wasted API calls
**Location:** `libs/agno/agno/knowledge/knowledge.py`
- Async (`_aload_from_url`): lines 1527-1559
- Sync (`_load_from_url`): lines 1683-1715
**Since:** v2.5.0
**Status:** Open

**Description:**
Three failure modes in both `_aload_from_url` and `_load_from_url`:

**(a) URL validation fails (no scheme/netloc):** Status set to FAILED, but NO `return`. Execution falls through to `url_path = Path(parsed_url.path)` and fetch proceeds on a known-bad URL — wasted API call.

**(b) URL validation exception:** Status set to FAILED, but NO `return`. Falls through to `url_path = Path(parsed_url.path)` where `parsed_url` is UNDEFINED (the `urlparse()` call itself threw) — `NameError` crash.

**(c) Fetch exception (network error, timeout):** No try/except around `async_fetch_with_retry()` / `fetch_with_retry()`. Network errors crash all the way up to `ainsert()`/`insert()` with no status update, no cleanup. Verified call chain: `ainsert()` → `_aload_content()` → `_aload_from_url()` → `async_fetch_with_retry()` — no try/except anywhere in the chain.

Both sync and async versions have all 3 failure modes.

**Fix required (3 parts):**
1. Add `return` after `log_warning()` in both the `if not all(...)` and `except` branches
2. Wrap fetch at line ~1547-1550 (async) / ~1695-1697 (sync) in try/except with FAILED status + return
3. Same fix in both `_aload_from_url()` and `_load_from_url()`

---

### BUG-006: Knowledge content hash collision across named instances

**Severity:** HIGH — silent data loss (second instance gets zero documents)
**Location:** `libs/agno/agno/knowledge/knowledge.py` — `_build_content_hash` (:2143) and `_build_document_content_hash` (:2207)
**Since:** v2.5.0 (when `linked_to` was introduced)
**Status:** Fixed — PR #6482
**PR:** https://github.com/agno-agi/agno/pull/6482

**Description:**
Two Knowledge instances sharing the same VectorDB that index the same file produce identical content hashes. The hash is computed from `content.name + content.url/path` — it doesn't include the Knowledge instance name. When the second instance tries to index, `skip_if_exists` sees the hash already exists and silently skips. The second instance has zero documents.

**Fix:** Include `self.name` in `hash_parts` when `isolate_vector_search=True`.

---

### BUG-007: Knowledge content-by-ID operations bypass isolation (IDOR)

**Severity:** HIGH — cross-instance data access
**Location:** `libs/agno/agno/knowledge/knowledge.py`
- `get_content_by_id` (:642)
- `aget_content_by_id` (:656)
- `get_content_status` (:672)
- `aget_content_status` (:688)
**Since:** v2.5.0
**Status:** Fixed — PR #6482

**Description:**
All four content-by-ID methods fetch by ID without checking whether the content's `linked_to` field matches the requesting Knowledge instance. If you know a content_id belonging to "KB-A", you can call `kb_b.get_content_by_id(that_id)` and access it — classic IDOR.

**Fix:** After fetching the row, check `self.isolate_vector_search and self.name and getattr(content_row, "linked_to", None) != self.name` and return None if it doesn't match.

---

### BUG-008: Knowledge list-based filters bypass isolation

**Severity:** HIGH — isolation silently broken for FilterExpr users
**Location:** `libs/agno/agno/knowledge/knowledge.py`
- `search` (:530)
- `asearch` (:570)
**Since:** v2.5.0
**Status:** Fixed — PR #6482

**Description:**
The search methods only injected `linked_to` for `None` or `dict` filters. List-based `FilterExpr` filters (e.g., `[EQ("category", "docs")]`) silently skipped isolation — the code had a comment saying "user must add linked_to filter manually."

**Fix:** Added `elif isinstance(search_filters, list): search_filters = [*search_filters, EQ("linked_to", self.name)]`.

---

### BUG-009: AsyncClient missing follow_redirects for URL content fetching

**Severity:** MEDIUM — async URL indexing fails on redirects
**Location:** `libs/agno/agno/knowledge/knowledge.py:1559`
**Since:** v2.5.0
**Status:** Fixed — PR #6482

**Description:**
`httpx.AsyncClient()` defaults to `follow_redirects=False`. URLs that return 307 redirects (common with CDNs, S3 presigned URLs, URL shorteners) fail silently in the async path.

**Fix:** `AsyncClient(follow_redirects=True)`.

---

### BUG-010: Async search sync fallback blocks event loop

**Severity:** MEDIUM — server freezes during search in async deployments
**Location:** `libs/agno/agno/knowledge/knowledge.py:581`
**Since:** v2.5.0
**Status:** Fixed — PR #6482

**Description:**
When `async_search()` raises `NotImplementedError`, the sync fallback was called directly: `return self.vector_db.search(...)`. This blocks the event loop for the duration of the vector DB query. In a FastAPI server, this serializes all concurrent requests.

**Fix:** `return await asyncio.to_thread(self.vector_db.search, ...)`.

---

### BUG-011: Memory update_memory missing user_id/agent_id/team_id

**Severity:** HIGH — memory updates lose user association, cross-user memory corruption possible
**Location:** `libs/agno/agno/memory/manager.py`
- Sync `update_memory`: lines 1355-1364 (inside `_get_db_tools`)
- Async `update_memory`: lines 1477-1495 (inside `_aget_db_tools`)
**Since:** at least v2.3.13 (user report), still present on main as of 2026-02-13
**Status:** REPRODUCED — confirmed on `origin/main`
**Issue:** https://github.com/agno-agi/agno/issues/5735 (open, stale)
**Reproduction:** `tests/unit/memory/test_memory_update_bug.py` — 8 tests confirm missing fields via source inspection. Sync `update_memory` missing `agent_id`, `team_id`. Async `update_memory` missing `user_id`, `agent_id`, `team_id`. Async `delete_memory` missing `user_id` (ownership bypass).

**Description:**
The memory tool functions (used by the LLM to manage stored memories) have incomplete field passing compared to `add_memory`:

| Function | `user_id` | `agent_id` | `team_id` |
|----------|-----------|------------|-----------|
| Sync `add_memory` (:1322) | Yes | Yes | Yes |
| Sync `update_memory` (:1355) | Yes | **Missing** | **Missing** |
| Sync `delete_memory` (:1370) | Yes | n/a | n/a |
| Async `add_memory` (:1431) | Yes | Yes | Yes |
| Async `update_memory` (:1477) | **Missing** | **Missing** | **Missing** |
| Async `delete_memory` (:1510) | **Missing** | n/a | n/a |

**update_memory:** The async version loses ALL three identifiers. When `user_id` is missing, the memory is stored without user association. In a multi-user deployment, updated memories become orphaned or could be associated with the wrong user. The sync version retains `user_id` but loses `agent_id` and `team_id`.

**delete_memory (new finding, R8):** The async `delete_memory` does NOT pass `user_id` to `delete_user_memory()`. Multiple DB backends (Mongo, In-Memory, Redis, Firestore, GCS, JSON, GCS-JSON) use this parameter to **verify ownership** before allowing deletion. Without it, the ownership check is skipped — any user can delete another user's memories via the async path.

**User report (issue #5735):** A user with MongoDB backend confirmed that calling `update_memory` sets both `user_id` and `agent_id` to null. The issue is open and unfixed since 2025-12-17.

**Confirmed on main (2026-02-13):** Verified via `git show origin/main:libs/agno/agno/memory/manager.py` — the missing fields are present on current main. The `add_memory` function at lines 1325-1334 includes `user_id`, `agent_id`, `team_id`. The `update_memory` function at lines 1357-1365 omits `agent_id` and `team_id`. The async `update_memory` at lines 1480-1495 omits all three.

**Fix:** Three changes needed:
- Sync `update_memory`: add `agent_id=agent_id, team_id=team_id` to `UserMemory(...)` (~line 1357)
- Async `update_memory`: add `user_id=user_id, agent_id=agent_id, team_id=team_id` to BOTH `UserMemory(...)` constructions (~lines 1480, 1488)
- Async `delete_memory`: add `user_id=user_id` to BOTH `delete_user_memory()` calls (~line 1510)

---

---

### BUG-013: Workflow stream_events `or` pattern (same as FIXED-002)

**Severity:** MEDIUM — explicit `stream_events=False` silently overridden
**Location:** `libs/agno/agno/workflow/workflow.py`
- Sync: line 3982
- Async: line 4199
**Since:** v2.5.0
**Status:** REPRODUCED
**Reproduction:** `tests/unit/workflow/test_stream_events_bug.py` — 3 tests confirm `False or True == True` semantics and that the buggy `or` pattern exists in Workflow source.

**Description:**
Same Python `or` operator bug as FIXED-002 (debug_mode in hooks):
```python
stream_events = stream_events or self.stream_events
```

When called with `stream_events=False` (falsy), Python `or` evaluates to `self.stream_events`. If the workflow has `stream_events=True`, the explicit `False` argument is silently ignored.

The `stream` parameter on the line above is handled correctly with `if stream is None:`, but `stream_events` uses the broken `or` pattern.

**Additional instances (found in Round 5):** Same pattern in team delegation tools — `stream_events or team.stream_member_events` where `stream_events: bool = False`:
- `libs/agno/agno/team/_default_tools.py:512, 652, 781, 910`
- `libs/agno/agno/team/_task_tools.py:333, 467`

In these 6 locations, the `stream_events` parameter has type `bool = False` (not `Optional[bool]`), so the `or` always falls through to `team.stream_member_events` when the default is used. A caller cannot explicitly disable stream_events for member agent calls if the team has `stream_member_events=True`.

**Fix:** Change all locations to use None-aware pattern:
```python
stream_events = stream_events if stream_events is not None else self.stream_events
```
For team tools, the parameter type should change from `bool = False` to `Optional[bool] = None`.

---

### BUG-014: MongoDB async_drop missing search index cleanup

**Severity:** MEDIUM — orphaned search indexes on async drop
**Location:** `libs/agno/agno/vectordb/mongodb/mongodb.py`
- Async `async_drop`: lines 1221-1230
- Sync `drop`: lines 924-959
**Since:** v2.5.0
**Status:** Open

**Description:**
The sync `drop()` method properly handles search index cleanup before dropping the collection:
- For Cosmos DB: calls `collection.drop_index(index_name)` (line 937)
- For MongoDB Atlas: calls `collection.drop_search_index(index_name)` with a 2-second wait (line 948-949)

The async `async_drop()` method simply drops the collection with no index cleanup:
```python
async def async_drop(self) -> None:
    if await self.async_exists():
        collection = await self._get_async_collection()
        await collection.drop()  # No index cleanup!
```

This leaves orphaned search indexes in MongoDB Atlas / Cosmos DB. On Atlas, orphaned indexes count against the index limit and can prevent creating new indexes on a new collection with the same name.

**Fix:** Port the sync index cleanup logic to `async_drop()`:
```python
async def async_drop(self) -> None:
    if await self.async_exists():
        collection = await self._get_async_collection()
        # Clean up search indexes before dropping
        if self.cosmos_compatibility:
            if self._search_index_exists():
                index_name = self.search_index_name or "vector_index_1"
                await collection.drop_index(index_name)
        else:
            if self._search_index_exists():
                index_name = self.search_index_name or "vector_index_1"
                await collection.drop_search_index(index_name)
                await asyncio.sleep(2)
        await collection.drop()
```

---

### BUG-015: Reasoning always reports success=True even on failure

**Severity:** HIGH — callers trust incomplete/failed reasoning output
**Location:** `libs/agno/agno/reasoning/manager.py`
- Sync: lines 883-887
- Async: lines 985-989
**Since:** v2.5.0
**Status:** REPRODUCED
**Reproduction:** `tests/unit/reasoning/test_reasoning_success_bug.py` — 5 tests confirm: (1) final yield after loop always has `success=True`, (2) no variable tracks loop error state, (3) 4+ break paths exit without setting failure, (4) async variant has same pattern, (5) native reasoning correctly uses `success=False` (control).

**Description:**
The reasoning loop can `break` on three failure conditions:
1. Empty response (lines 831-833 / 938-940)
2. Content is string instead of structured output (lines 836-837 / 942-944)
3. Exception during reasoning (lines 865-867 / 969-971)

After the loop, the result is always emitted with `success=True`:
```python
yield (
    None,
    ReasoningResult(
        steps=all_reasoning_steps,
        reasoning_messages=reasoning_messages,
        success=True,  # ← hardcoded, never set to False
    ),
)
```

Callers use `success` to decide whether to trust the reasoning output. Failed reasoning (zero or partial steps) is reported as successful, leading to downstream decisions made on incomplete/invalid reasoning data.

**Fix:** Track a `reasoning_succeeded` flag, set to `False` on error/break, pass to `ReasoningResult(success=reasoning_succeeded)`.

---

### BUG-016: `or`+ternary precedence causes ID collisions across DB/vectordb modules

**Severity:** MEDIUM — non-unique IDs when multiple instances point to different databases
**Location:** Multiple files:
- `libs/agno/agno/db/sqlite/sqlite.py:101`
- `libs/agno/agno/db/sqlite/async_sqlite.py:96`
- `libs/agno/agno/db/singlestore/singlestore.py:89`
- `libs/agno/agno/db/mysql/async_mysql.py:90`
- `libs/agno/agno/vectordb/weaviate/weaviate.py:60`
**Since:** v2.5.0
**Status:** REPRODUCED
**Reproduction:** `tests/unit/db/test_db_id_bugs.py` — 3 tests confirm: (1) `SqliteDb(db_url="sqlite:///db1.db")` and `SqliteDb(db_url="sqlite:///db2.db")` get same ID, (2) same for different `db_file` values, (3) direct proof that ternary precedence causes `db_url` to be ignored when `db_engine` is None.

**Description:**
Python operator precedence parses `a or b if c else d` as `(a or b) if c else d`, not the intended `a or (b if c else d)`.

Example from sqlite.py:101:
```python
seed = db_url or db_file or str(db_engine.url) if db_engine else "sqlite:///agno.db"
# Parsed as: (db_url or db_file or str(db_engine.url)) if db_engine else "sqlite:///agno.db"
```

When `db_engine=None` (common — engine created later in `__init__`), the entire `db_url or db_file or ...` chain is skipped and seed defaults to `"sqlite:///agno.db"`, regardless of what `db_url` or `db_file` was provided.

**Impact:** All SqliteDb instances without explicit `id` get the same generated ID. Same for Weaviate cloud instances (`wcd_url` ignored when `local=False`), SingleStore, async SQLite, async MySQL.

**Fix:** Add parentheses to all affected locations:
```python
seed = db_url or db_file or (str(db_engine.url) if db_engine else "sqlite:///agno.db")
```

---

### BUG-017: `exit(1)` in library code terminates host process

**Severity:** MEDIUM — kills FastAPI servers, Jupyter notebooks, any host process
**Location:** 5 files:
- `libs/agno/agno/memory/manager.py:109`
- `libs/agno/agno/culture/manager.py:90`
- `libs/agno/agno/api/settings.py:50`
- `libs/agno/agno/team/_init.py:512`
- `libs/agno/agno/cloud/aws/s3/api_client.py:36` (uses `exit(0)` — even more confusing as it signals success)
**Since:** v2.0.0
**Status:** REPRODUCED
**Reproduction:** `tests/unit/test_exit_bugs.py` — blocks `openai` import, confirms `MemoryManager.get_model()` raises `SystemExit(1)` instead of an importable exception.

**Description:**
When `openai` is not installed and no explicit model is configured, the code calls `exit(1)` instead of raising an exception:
```python
except ModuleNotFoundError as e:
    log_error(e)
    log_error("Agno uses `openai` as the default model provider...")
    exit(1)
```

`exit(1)` raises `SystemExit`, which terminates the entire host process. In a FastAPI server or Jupyter notebook, this kills the server/kernel. A library should never call `exit()` — it should raise `ImportError` or `RuntimeError` and let the caller handle it.

Found in 5 locations across memory manager, culture manager, API settings, team init, and S3 API client. The S3 variant uses `exit(0)` which is even more confusing — it signals success exit code while the operation actually failed.

**Fix:** Replace `exit(1)` / `exit(0)` with `raise ImportError("...")` or `raise RuntimeError("...")` in all 5 locations.

---

### BUG-018: VectorDb async_upsert signature mismatch (3 implementations)

**Severity:** LOW — affects only unimplemented adapters, would get TypeError instead of NotImplementedError
**Location:**
- Base class contract: `libs/agno/agno/vectordb/base.py:70-72` — `async_upsert(self, content_hash, documents, filters)`
- Broken signatures:
  - `libs/agno/agno/vectordb/langchaindb/langchaindb.py:70` — `async_upsert(self, documents, filters)`
  - `libs/agno/agno/vectordb/llamaindex/llamaindexdb.py:68` — `async_upsert(self, documents, filters)`
  - `libs/agno/agno/vectordb/lightrag/lightrag.py:92` — `async_upsert(self, documents, filters)`
**Since:** v2.5.0
**Status:** Open

**Description:**
Three vectordb adapter implementations define `async_upsert` without the `content_hash` parameter that the base class requires. If called through the `VectorDb` interface with `content_hash` as a keyword argument, these would raise `TypeError: unexpected keyword argument 'content_hash'` instead of the intended `NotImplementedError`.

All three implementations are stubs (raise NotImplementedError or `pass`), so the practical impact is wrong error type rather than wrong behavior. But it violates the Liskov Substitution Principle and would confuse users debugging adapter issues.

**Fix:** Add `content_hash: str` as first parameter to all three implementations.

### BUG-019: Team sync hooks missing `iscoroutinefunction` check

**Severity:** HIGH — async hooks silently don't execute in sync context
**Location:** `libs/agno/agno/team/_hooks.py`
- `_execute_pre_hooks` (sync): line 276 — no check
- `_execute_post_hooks` (sync): line 467 — no check
**Since:** v2.5.0
**Status:** REPRODUCED
**Reproduction:** `tests/unit/team/test_team_hook_bugs.py` — 3 tests confirm: (1) `_execute_pre_hooks` source has no `iscoroutinefunction` check, (2) calling an async function without `await` returns an unawaited coroutine and the body never executes, (3) sync hooks work correctly (control).

**Description:**
Agent hooks correctly check for async functions before calling them in sync context (`agent/_hooks.py:110-114`):
```python
if iscoroutinefunction(hook):
    log_warning(f"Async hook '{hook.__name__}' cannot be used with sync run(). Use arun() instead. Skipping hook.")
    continue
```

Team sync hook executors (`_execute_pre_hooks` at line 276, `_execute_post_hooks` at line 467) skip this check entirely — they call `hook(**filtered_args)` directly. If a user provides an `async def` hook in `team.pre_hooks` or `team.post_hooks` and calls `team.run()` (sync), the call returns a coroutine object that is never awaited. The hook silently fails to execute.

The team's OWN async executors (`_aexecute_pre_hooks` at line 369, `_aexecute_post_hooks` at line 557) DO have the `iscoroutinefunction` check and properly `await` async hooks. This is a parity gap between sync and async team hook execution.

**Impact:** Any async hook (including guardrails) provided to a team running in sync mode will appear to succeed but never actually run. Python may emit a `RuntimeWarning: coroutine was never awaited` to stderr, but no framework-level warning or error is raised.

**Fix:** Add the same `iscoroutinefunction` check to `_execute_pre_hooks` and `_execute_post_hooks`, matching the agent pattern.

### BUG-020: Session deserialization IndexError on empty `runs` list

**Severity:** MEDIUM — crash during session load with empty runs
**Location:**
- `libs/agno/agno/session/agent.py:62`
- `libs/agno/agno/session/team.py:65`
**Since:** v2.5.0
**Status:** REPRODUCED
**Reproduction:** `tests/unit/session/test_session_bugs.py` — 5 tests confirm: (1) `AgentSession.from_dict({"session_id": "x", "runs": []})` raises `IndexError`, (2) same for `TeamSession`, (3) `runs=None` and missing `runs` key work fine (controls).

**Description:**
Both `AgentSession.from_dict()` and `TeamSession.from_dict()` check runs type with:
```python
if runs is not None and isinstance(runs[0], dict):
```

When `runs` is an empty list `[]`, `runs is not None` is True but `runs[0]` raises `IndexError`. The fix is trivial: add `len(runs) > 0` or use `runs and isinstance(runs[0], dict)`.

**Additional issue in team.py:61:** `data["summary"] = SessionSummary.from_dict(data["summary"])` mutates `data`, which is typed as `Mapping[str, Any]` (immutable contract). If `data` comes from a SQLAlchemy row mapping or frozen dict, this raises `TypeError`.

**Fix:**
1. Change both `runs[0]` checks to `runs and isinstance(runs[0], dict)`
2. In team.py, assign to a local variable instead of mutating `data`

### BUG-021: OpenAI Responses `_create_vector_store` — infinite loop + blocking sleep in async path

**Severity:** HIGH — can hang forever, blocks event loop in async context
**Location:** `libs/agno/agno/models/openai/responses.py:351-364`
**Since:** v2.5.0
**Status:** Open

**Description:**
```python
while True:
    uploaded_files = self.get_client().vector_stores.files.list(...)
    ...
    if all_completed or failed:
        break
    time.sleep(1)
```

Two issues:
1. **No timeout/max iterations:** If OpenAI API never returns `completed` status for uploaded files, this loops forever.
2. **`time.sleep(1)` blocks the event loop in async context:** Call chain: `ainvoke()` → `get_request_params()` → `_format_tool_params()` → `_create_vector_store()`. All methods are sync (no async variant), so `time.sleep(1)` blocks the entire event loop during every async file-search request.

**Fix:**
1. Add a timeout/max iterations (e.g., 60 seconds)
2. Create an async variant `_acreate_vector_store` using `asyncio.sleep(1)` and async OpenAI client
3. Use the async variant from `ainvoke()`'s code path

### BUG-022: Team delegation `child_run_id` overwritten for all tool entries

**Severity:** MEDIUM — corrupts delegation lineage when multiple members are delegated to in one response
**Location:** `libs/agno/agno/team/_default_tools.py:430-433`
**Since:** v2.5.0
**Status:** Open

**Description:**
After each member delegation completes, the code updates the parent's tool call record:
```python
for tool in run_response.tools:
    if tool.tool_name and tool.tool_name.lower() == "delegate_task_to_member":
        tool.child_run_id = member_agent_run_response.run_id
```

This iterates ALL tool entries named `delegate_task_to_member` and sets them ALL to the latest member's `run_id`. When the model delegates to multiple members in one response (e.g., "delegate to researcher AND writer"), each delegation overwrites ALL matching entries. The final state is: every delegation tool record points to the LAST member's run, losing the correct lineage for earlier delegations.

**Fix:** Match on `tool.tool_call_id` (unique per tool call) instead of just `tool_name`.

### BUG-023: Scheduler per-schedule timeout ignored for simple HTTP requests

**Severity:** LOW — only affects non-run-endpoint schedules
**Location:** `libs/agno/agno/scheduler/executor.py:254, 285`
**Since:** v2.5.0
**Status:** Open

**Description:**
```python
timeout_seconds = schedule.timeout_seconds or self.timeout  # line 254 — computed
...
return await self._simple_request(client, method, url, headers, payload)  # line 285 — not passed
```

Per-schedule `timeout_seconds` is computed at line 254 but never passed to `_simple_request()`. The shared HTTP client uses `self.timeout` (set at construction), ignoring any per-schedule timeout configuration for non-run endpoints. Additionally, `schedule.timeout_seconds=0` is treated as falsy due to the `or` pattern.

For run endpoints (lines 274-282), `timeout_seconds` IS correctly passed to `_background_run` → `_poll_run`.

**Fix:** Add `timeout_seconds` parameter to `_simple_request` and pass it to `client.request()`.

---

### BUG-024: Gemini audio/video formatting blocks async event loop + no timeout

**Severity:** HIGH — blocks event loop, potential infinite loop
**Location:** `libs/agno/agno/models/google/gemini.py`
- `_format_audio_for_message`: lines 890-893
- `_format_video_for_message`: lines 942-946
**Since:** v2.5.0
**Status:** Open

**Description:**
Same bug class as BUG-021 (OpenAI Responses `_create_vector_store`). Two sync methods have `while` loops with `time.sleep(2)` that are called from async code paths:

```python
# _format_audio_for_message (line 890-893):
while audio_file.state and audio_file.state.name == "PROCESSING":
    if audio_file.name:
        audio_file = self.get_client().files.get(name=audio_file.name)
    time.sleep(2)  # Blocks event loop!

# _format_video_for_message (line 942-946):
while video_file.state and video_file.state.name == "PROCESSING":
    if video_file.name:
        video_file = self.get_client().files.get(name=video_file.name)
    time.sleep(2)  # Blocks event loop!
```

**Call chain from async:** `ainvoke()` (line 583) → `_format_messages()` (line 597) → `_format_video_for_message()` / `_format_audio_for_message()`.

Two issues:
1. **Blocks event loop:** `time.sleep(2)` in methods called from `ainvoke()` blocks the entire event loop. In a FastAPI server, this serializes all concurrent requests while waiting for Gemini file processing.
2. **No timeout:** Unlike `wait_for_operation()` (line 1612) which has `max_wait=600`, these `while` loops have no timeout or max iterations. If the Gemini API never returns `completed` status, the loop runs forever.

**Note:** The `wait_for_operation()` / `async_wait_for_operation()` pair at lines 1612/1639 is correctly implemented with proper timeout and `asyncio.sleep`. The file formatting methods missed this pattern.

**Fix (3 parts):**
1. Add timeout to both while loops (matching `wait_for_operation` pattern):
   ```python
   elapsed = 0
   max_wait = 120  # 2 minutes
   while audio_file.state and audio_file.state.name == "PROCESSING":
       if elapsed >= max_wait:
           log_error(f"Audio file processing timed out after {max_wait}s")
           return None
       if audio_file.name:
           audio_file = self.get_client().files.get(name=audio_file.name)
       time.sleep(2)
       elapsed += 2
   ```
2. Create async variants `_aformat_audio_for_message` / `_aformat_video_for_message` using `asyncio.sleep(2)` and `self.get_client().aio.files.get()`
3. Create `_aformat_messages` that calls the async variants, and use it from `ainvoke()` / `ainvoke_stream()`

---

### BUG-025: WebSearchReader async_read blocks event loop with sync search call

**Severity:** HIGH — blocks event loop during web search in async context
**Location:** `libs/agno/agno/knowledge/reader/web_search_reader.py:267`
**Since:** v2.5.0
**Status:** Open

**Description:**
The `async_read()` method (line 260) calls `self._perform_web_search(query)` at line 267 — a synchronous method that chains into `_perform_duckduckgo_search()` which contains multiple `time.sleep()` calls:
- Line 79: `time.sleep(sleep_time)` in `_respect_rate_limits()`
- Line 116: `time.sleep(wait_time)` on rate limit retry
- Line 119: `time.sleep(self.search_delay)` on other error retry

```python
async def async_read(self, query: str) -> List[Document]:
    # ...
    search_results = self._perform_web_search(query)  # BLOCKING in async context!
    # ...
    # Rest of method is properly async:
    for i, result in enumerate(search_results):
        await asyncio.sleep(self.delay_between_requests)  # Correct
        doc = await fetch_url_async(result)  # Correct
```

The rest of `async_read()` is properly async — URL fetching uses `httpx.AsyncClient`, delays use `asyncio.sleep`. Only the initial search step blocks.

**Impact:** In a FastAPI server using async knowledge indexing with web search, the event loop blocks during the DuckDuckGo search + rate limiting. With exponential backoff, this could block for 30+ seconds.

**Fix:** Wrap the blocking call:
```python
search_results = await asyncio.to_thread(self._perform_web_search, query)
```

This matches the pattern used by other readers (WikipediaReader, ArxivReader, S3Reader all use `asyncio.to_thread()` or `run_in_executor()`).

---

### BUG-026: Hook normalization state leak between sync and async run modes

**Severity:** MEDIUM — wrong hook callables used in second run mode
**Location:** `libs/agno/agno/agent/_run.py`, `libs/agno/agno/team/_run.py`
**Since:** v2.5.0 (when hooks normalization was added)
**Status:** Open

**Description:**
The `_hooks_normalised` flag is a single boolean shared between sync and async execution paths. Whichever run mode (sync or async) is called first normalizes the hooks for that mode and sets the flag to True. When the second mode is called, it sees the flag is already True and skips normalization — using hooks prepared for the wrong mode.

`normalize_pre_hooks()` produces different callables depending on `async_mode`:
- `async_mode=False` → wraps guardrails with `.check()` (sync callable)
- `async_mode=True` → wraps guardrails with `.async_check()` (async callable)

If sync `run()` is called first, hooks are normalized with sync callables. A subsequent `arun()` reuses those sync callables in an async context.

**Fix:** Use separate flags (`_hooks_normalised_sync`, `_hooks_normalised_async`) or normalize lazily per-mode.

---

### BUG-027: WhatsApp signature validation defaults to development mode

**Severity:** HIGH — security bypass in production deployments
**Location:** `libs/agno/agno/os/interfaces/whatsapp/security.py`
**Since:** Initial WhatsApp interface implementation
**Status:** Open

**Description:**
`is_development_mode()` returns True when `APP_ENV` is not set (defaults to "development"), causing HMAC-SHA256 signature validation to be bypassed. Any production deployment that doesn't explicitly set `APP_ENV=production` will accept arbitrary webhook payloads without signature verification.

```python
def is_development_mode():
    return os.getenv("APP_ENV", "development") == "development"  # True when unset
```

**Fix:** Default to production mode (require explicit opt-in to development mode):
```python
def is_development_mode():
    return os.getenv("APP_ENV", "production") == "development"
```

---

### BUG-028: A2A non-stream endpoint calls entity.arun() without await

**Severity:** MEDIUM — deprecated endpoint returns coroutine object instead of RunOutput
**Location:** `libs/agno/agno/os/interfaces/a2a/router.py:~876, ~887`
**Since:** A2A interface implementation
**Status:** Open

**Description:**
The deprecated non-stream A2A endpoint calls `entity.arun()` (an async method) without `await`, producing a coroutine object that gets assigned to `response` instead of the actual `RunOutput`. Downstream code that accesses `response.content` or `response.messages` will fail or return unexpected results.

```python
response = entity.arun(...)  # Missing await — returns coroutine, not RunOutput
```

Only affects the deprecated non-stream path; the current streaming path works correctly.

**Fix:** Add `await`:
```python
response = await entity.arun(...)
```

---

### BUG-029: AccuracyResult dataclass fields uninitialized when results list is empty

**Severity:** LOW — edge case with empty evaluation results
**Location:** `libs/agno/agno/eval/accuracy.py`
**Since:** Evaluation framework implementation
**Status:** Open

**Description:**
`AccuracyResult` declares stat fields like `avg_score`, `mean_score`, etc. with `field(init=False)` but only sets them inside `compute_stats()` when the results list is non-empty. If constructed with `results=[]`, these fields remain unset, and any access raises `AttributeError`.

The `print_summary()` method checks `if self.avg_score is not None` — but `avg_score` doesn't exist at all (it's not None, it's undefined), so this check itself raises `AttributeError`.

**Fix:** Set default values in `__post_init__` or provide `field(init=False, default=None)`.

---

### BUG-030: ReliabilityEval has three tool call aggregation issues

**Severity:** MEDIUM — incorrect evaluation results for tool-calling agents
**Location:** `libs/agno/agno/eval/reliability.py`
**Since:** Evaluation framework implementation
**Status:** Open

**Description:**
Three related issues in tool call evaluation:

**(a) List mutation via `+=`:**
```python
messages = self.team_response.messages or []  # Reference, not copy
messages += member_response.messages           # Mutates original list
```
This permanently modifies `team_response.messages` with each member's messages appended.

**(b) Only first tool_call captured:**
```python
actual_tool_calls.append(message.tool_calls[0])  # Drops tool_calls[1:]
```
Messages with multiple tool calls only have their first call captured.

**(c) Missing expected calls not detected:**
The evaluation checks if actual calls are in the expected list (flags unexpected calls), but never checks if expected calls are missing from the actual list. An agent that calls none of the expected tools would pass evaluation.

---

### BUG-031: AgentOS.serve() overwrites user-provided reload_includes

**Severity:** LOW — development-mode annoyance
**Location:** `libs/agno/agno/os/app.py:~1343`
**Since:** AgentOS implementation
**Status:** Open

**Description:**
The condition `if reload and reload_includes is not None:` is inverted. When the user provides custom `reload_includes`, the condition is True and overwrites them with `["*.yaml", "*.yml"]`. When the user doesn't provide includes (None), the condition is False and the defaults are NOT applied.

```python
if reload and reload_includes is not None:    # Bug: should be `is None`
    reload_includes = ["*.yaml", "*.yml"]      # Overwrites user's custom includes
```

**Fix:** Change to `is None`:
```python
if reload and reload_includes is None:
    reload_includes = ["*.yaml", "*.yml"]
```

---

### BUG-032: WorkflowSession.workflow_name lost in DB round-trip

**Severity:** LOW — metadata loss, no functional impact
**Location:** `libs/agno/agno/db/sqlite/sqlite.py` (upsert_session), similar in other DB adapters
**Since:** WorkflowSession implementation
**Status:** Open (GitHub issue #4678 — closed but unfixed)

**Description:**
`WorkflowSession.to_dict()` serializes `workflow_name`, but DB adapters (SQLite, PostgreSQL, etc.) don't include `workflow_name` in the upsert values dict. The field is lost on DB write and comes back as None on read.

**Fix:** Add `workflow_name` to the upsert values in all DB adapters' `upsert_session` methods.

---

### BUG-033: AgentSession.team_id and workflow_id lost in DB round-trip

**Severity:** LOW — metadata loss, no functional impact
**Location:** `libs/agno/agno/db/sqlite/sqlite.py` (upsert_session), similar in other DB adapters
**Since:** AgentSession implementation
**Status:** Open (GitHub issue #5883 — closed but unfixed)

**Description:**
`AgentSession.to_dict()` serializes `team_id` and `workflow_id`, but DB adapters don't include these fields in the upsert values dict. The fields are lost on DB write and come back as None on read.

**Fix:** Add `team_id` and `workflow_id` to the upsert values in all DB adapters' `upsert_session` methods.


## Bugs Fixed on fix/hooks-guardrails Branch

These bugs are fixed in commit `71939a086` on the `fix/hooks-guardrails` branch but not yet merged to main.

### FIXED-001: Guardrails bypass when `_run_hooks_in_background=True`

**Severity:** CRITICAL — security guardrails silently bypassed
**Location:** `agent/_hooks.py` (pre: 80-87, post: 288-295), `team/_hooks.py` (pre: 249-255, post: 444-450)

**Description:**
When `_run_hooks_in_background=True`, ALL hooks (including guardrails) were sent to background tasks. Guardrails like PII detection need to run synchronously to propagate `InputCheckError`/`OutputCheckError`. In background mode, these exceptions were swallowed.

**Fix:** `is_guardrail_hook()` utility in `utils/hooks.py` detects guardrails (bound methods of `BaseGuardrail`) and forces synchronous execution even in background mode.

### FIXED-002: `debug_mode=False` overridden by `or` operator

**Severity:** MEDIUM
**Location:** All hook functions in `agent/_hooks.py` and `team/_hooks.py`

**Description:**
`debug_mode or agent.debug_mode` — when `debug_mode=False` (falsy), Python `or` evaluates to `agent.debug_mode`. An explicit `debug_mode=False` was ignored.

**Fix:** Changed to `debug_mode if debug_mode is not None else agent.debug_mode`.

### FIXED-003: Migration version stored even when migration skipped

**Severity:** HIGH — database version tracking corruption
**Location:** `db/migrations/manager.py:85-101`

**Description:**
`latest_version` was set unconditionally in the loop, and stored at the end even if no migration actually ran. Could cause migrations to be skipped on next run.

**Fix:** Track `any_migration_executed` flag; only store version if a migration actually succeeded.

### FIXED-004: PII email regex with `|` in character class

**Severity:** LOW
**Location:** `guardrails/pii.py:41`

**Description:**
`[A-Z|a-z]` — the `|` is a literal character inside `[]`, not alternation. Changed to `[A-Za-z]`.

### FIXED-005: PII masking assumes string input

**Severity:** LOW
**Location:** `guardrails/pii.py:63-69, 93-99`

**Description:**
`re.sub()` on `run_input.input_content` would crash with `TypeError` if input was not a string (e.g., a list of messages).

**Fix:** Added `isinstance(run_input.input_content, str)` check and warning log for non-string inputs.

---

## Suspected Issues (Not Yet Confirmed as Bugs)

### SUSPECT-001: No workflow-level execution timeout

**Severity:** LOW (operational, not data loss)
**Location:** `libs/agno/agno/workflow/workflow.py` (all execution paths)

**Description:**
Neither workflow execution nor individual step execution has a timeout wrapper. Steps that call Agent/Team `run`/`arun` can block indefinitely if the LLM call hangs.

Parallel execution has the same issue: `ThreadPoolExecutor` and `asyncio.gather` wait forever if one branch never completes.

**Observed in:** 3 cookbook timeouts (structured_io_team.py, step_history.py, metrics.py) — likely slow LLM calls rather than hangs, but no framework-level protection exists.

**Verdict:** Not a bug per se (callers should use external timeouts), but worth noting as a design gap.

### SUSPECT-002: Duplicate step names overwrite in previous_step_outputs

**Severity:** LOW
**Location:** `libs/agno/agno/workflow/workflow.py:1736`

**Description:**
`previous_step_outputs[step_name] = step_output` uses step name as dict key. If two steps have the same name, the second silently overwrites the first. The recursive search in `get_step_output()` can't find the first step's output.

**Practical impact:** Unlikely with proper naming, but possible with auto-generated names (e.g., unnamed Agents getting fallback names).

### SUSPECT-004: Workflow API copy-paste log message

**Severity:** COSMETIC
**Location:** `libs/agno/agno/api/workflow.py:28`

**Description:**
```python
log_debug(f"Could not create Team: {e}")
```
This is in `alog_workflow_run()`, a function that records workflow telemetry. The error message says "Could not create Team" but should say "Could not create Workflow". The corresponding `libs/agno/agno/api/team.py` correctly says "Team".

Copy-paste error — no functional impact since this is a debug log in a fire-and-forget telemetry function.

### SUSPECT-005: Reasoning step_count increment inconsistency

**Severity:** LOW — no functional impact
**Location:** `libs/agno/agno/reasoning/manager.py`
- Sync: `step_count += 1` at end of loop (line ~869)
- Async: `step_count += 1` at start of loop (line ~932, before try block)

**Description:**
The sync and async reasoning loops increment `step_count` at different points. In sync, it's incremented after the step completes; in async, it's incremented before the try block. Since `step_count` is only used as the loop counter for `max_steps` and is not read after the loop exits, this has no functional impact. But it means the two variants may exit with different final `step_count` values if someone later adds code that uses it post-loop.

### SUSPECT-007: Reasoning off-by-one in max_steps (N-1 iterations)

**Severity:** LOW — may be intentional naming
**Location:** `libs/agno/agno/reasoning/manager.py`
- Sync: lines 819, 826, 869
- Async: lines 923, 930, 932

**Description:**
```python
step_count = 1
while next_action == NextAction.CONTINUE and step_count < self.config.max_steps:
    # ... do step ...
    step_count += 1
```

With `max_steps=N`, the loop runs N-1 times: `step_count` starts at 1, increments at the end, loop exits when `step_count >= max_steps`. So `max_steps=1` gives zero iterations, `max_steps=3` gives 2 iterations.

This could be intentional (max_steps is 1-indexed exclusive upper bound) or a bug (user expects max_steps=3 to give 3 steps). The naming "max_steps" suggests "maximum number of steps" which would be wrong.

### SUSPECT-008: Weaviate async client closed on success but not on failure

**Severity:** LOW — inconsistent but not clearly buggy in either direction
**Location:** `libs/agno/agno/vectordb/weaviate/weaviate.py:508-534`

**Description:**
`get_async_client()` returns a cached client (`self.async_client`). In async search methods, `await client.close()` is called on the success path (line 529) but not in the `except` block (line 532-534). Since the client is cached/shared:
- Closing on success forces reconnection on next call (wasteful)
- Not closing on failure keeps the connection alive (fine for a shared client)

The inconsistency suggests the author didn't realize the client was shared. But neither path causes data loss — it's a performance issue at most.

### SUSPECT-011: Scheduler per-schedule timeout `or` pattern

**Severity:** LOW
**Location:** `libs/agno/agno/scheduler/executor.py:254`

**Description:**
`timeout_seconds = schedule.timeout_seconds or self.timeout` — `schedule.timeout_seconds=0` is treated as falsy, falling through to `self.timeout`. While `timeout=0` is unusual, the `or` pattern silently prevents it.

### SUSPECT-010: Shallow copy of session state in team delegation

**Severity:** MEDIUM if concurrent members mutate nested state
**Location:** `libs/agno/agno/team/_default_tools.py:498, 638, 768, 898, 995` (5 instances)

**Description:**
```python
member_session_state_copy = copy(run_context.session_state)  # shallow copy
```

Uses `copy()` (shallow) instead of `deepcopy()`. Nested dict/list objects in `session_state` are shared between the parent and member agent. If a member modifies `session_state["nested"]["key"]`, it also modifies the parent's state (and other members' copies). In concurrent async delegation, this enables race conditions on shared nested objects.

However, after delegation completes, `merge_dictionaries(run_context.session_state, member_session_state_copy)` merges changes back. The shallow copy may be intentional to allow members to communicate state changes to the parent. Whether this is a bug depends on the intended isolation model.

**Assessment:** Design tension between state isolation and state sharing. Keep as SUSPECT until the team confirms intended behavior.

### SUSPECT-009: WatsonX URL precedence — env var overrides constructor arg

**Severity:** LOW — affects only WatsonX users who both set `IBM_WATSONX_URL` env var AND pass `url=` to constructor
**Location:** `libs/agno/agno/models/ibm/watsonx.py:68`

**Description:**
```python
self.url = getenv("IBM_WATSONX_URL") or self.url      # line 68 — env wins
self.api_key = self.api_key or getenv("IBM_WATSONX_API_KEY")   # line 60 — constructor wins
self.project_id = self.project_id or getenv("IBM_WATSONX_PROJECT_ID")  # line 64 — constructor wins
```

Line 68 reverses the operand order compared to lines 60 and 64. For `api_key` and `project_id`, constructor args take priority over env vars (standard pattern). For `url`, the env var always wins, silently overriding any `url=` constructor argument.

The reversal is partly intentional — `url` has a hardcoded default `"https://eu-de.ml.cloud.ibm.com"` (line 51), so `self.url or getenv(...)` would never consult the env var. But the reversal creates a different problem: explicit constructor args are overridden by env.

**Assessment:** Design tension between "default value with env override" and "constructor args should win". Not clearly a bug but inconsistent with the rest of the framework. Keep as SUSPECT.

### SUSPECT-006: VectorDB async clients never explicitly closed

**Severity:** LOW — resource leak in long-running processes
**Location:** `libs/agno/agno/vectordb/redis/redisdb.py:110-118` (most visible), but pattern applies to MongoDB, Pinecone, etc.

**Description:**
`_async_redis_client = AsyncRedis.from_url(url)` at line 116 is created lazily and cached on `self`, but never explicitly closed. There is no `close()`, `__aexit__`, or `__del__` method on the class. The same pattern exists across all vectordb implementations — only Qdrant has a `close()` method.

For sync clients, Python GC handles cleanup adequately. For async clients, open connections may hold event loop resources that aren't reliably cleaned up by GC alone. In a long-running FastAPI server creating many short-lived vectordb instances, this could cause connection pool exhaustion.

**Assessment:** Codebase-wide design pattern, not a single-module bug. The framework relies on GC for client cleanup, which works for sync but is problematic for async. Keep as SUSPECT.

### SUSPECT-003: MCP cleanup swallows all exceptions

**Severity:** LOW
**Location:** `libs/agno/agno/tools/mcp/mcp.py:386-402`, `libs/agno/agno/tools/mcp/multi_mcp.py:374-383`

**Description:**
Session cleanup uses bare `except: pass` in exception handlers. Previously evaluated as FP-003 for the `close()` path. The `cleanup_run_session()` has the same pattern — exceptions during session cleanup are silently swallowed.

**Assessment:** Intentional defensive code (cleanup shouldn't crash the app), but masks resource leaks if session teardown fails repeatedly. Keep as SUSPECT.

---

### SUSPECT-013: Agent.deep_copy() skips non-serializable fields silently

**Severity:** LOW
**Location:** `libs/agno/agno/agent/agent.py` (deep_copy method)

**Description:**
`deep_copy()` uses model serialization (`model_dump` / `model_validate`) which silently drops non-serializable fields (custom objects, lambdas, open connections). The copy may look complete but lack runtime state like tool instances, MCP sessions, or custom header providers.

**Assessment:** By design for Pydantic models, but users calling `deep_copy()` may not expect silent field loss. Keep as SUSPECT.

### SUSPECT-014: Tracing span context not propagated to async tool executions

**Severity:** LOW
**Location:** `libs/agno/agno/tracing/` (multiple files)

**Description:**
When tools are executed asynchronously (via ThreadPoolExecutor or asyncio.gather), the tracing span context from the parent agent run may not propagate to tool execution spans. This could cause tool traces to appear as orphaned spans in observability backends.

**Assessment:** Depends on the tracing backend's context propagation model. Keep as SUSPECT.

### SUSPECT-015: Approval flow timeout has no configurable default

**Severity:** LOW
**Location:** `libs/agno/agno/approval/` (multiple files)

**Description:**
The HITL approval flow waits indefinitely for user input. There's no configurable timeout at the framework level — the only protection is caller-side timeouts (e.g., `asyncio.wait_for`). In a server context, a hung approval request could hold resources indefinitely.

**Assessment:** Design gap rather than bug. Keep as SUSPECT.


## Cookbook Bugs (Not Framework)

### CB-001: access_previous_outputs.py — wrong step name reference

**Location:** `cookbook/04_workflows/06_advanced_concepts/previous_step_outputs/access_previous_outputs.py:128`

**Description:**
`print_final_report` calls `get_step_content("create_comprehensive_report")` but is only used in the second workflow (`direct_steps_workflow`) where the actual step is auto-wrapped from `create_comprehensive_report_from_step_indices` — so the step name is `"create_comprehensive_report_from_step_indices"`, not `"create_comprehensive_report"`.

This causes `get_step_content()` to return None, then `len(comprehensive_report)` at line 143 raises `TypeError: object of type 'NoneType' has no len()`.

**Fix:** Change the lookup to match the function name:
```python
comprehensive_report = step_input.get_step_content("create_comprehensive_report_from_step_indices")
```

---

### CB-002: async_mongodb_for_agent.py — double asyncio.run()

**Location:** `cookbook/06_storage/mongo/async_mongo/async_mongodb_for_agent.py:45-46`

**Description:**
Script calls `asyncio.run()` twice sequentially — once for database setup, once for agent execution. Same anti-pattern we fixed in the postgres and sqlite async cookbooks during the v2.5 audit. MongoDB was skipped because the service wasn't available locally for testing.

**Fix:** Wrap both calls in a single `async def main()` and call `asyncio.run(main())` once.

**Note:** Not a crash in Python 3.12+ (asyncio.run() can be called multiple times), but it's a best-practice violation and will crash on Python 3.11 and below.

---

## Verified Non-Bugs (False Positives from Codex)

### FP-001: async_gen_wrapper returns instead of yielding

**Codex claim:** `decorator.py:196` — wrapper returns generator object instead of yielding values.
**Actual behavior:** Works by accident. The coroutine wrapper returns an async generator object. `aexecute()` treats it as a coroutine (`await` it), gets the generator back, and downstream code (`base.py:2436`) correctly identifies it as `AsyncGeneratorType` and iterates it with `async for`. Error handling during iteration is handled at `base.py:2498`.
**Verdict:** Code quality issue (dead try/except), not a functional bug.

### FP-002: Parallel branches share mutable session_state

**Codex claim:** `parallel.py:293` — race condition from shared dict reference.
**Actual behavior:** Intentional design. Lines 292-294 explicitly share `run_context.session_state` by reference with a comment explaining why. Parallel steps are meant to see each other's state mutations.
**Verdict:** Working as designed.

### FP-003: MCPTools.__aexit__ doesn't clean _run_sessions

**Codex claim:** `mcp.py:538` — per-run sessions leak on context manager exit.
**Actual behavior:** `close()` at lines 508-512 iterates and closes all `_run_sessions`. `__aexit__` calls `close()` indirectly through the client shutdown. The primary cleanup path works.
**Verdict:** Not a leak.

### FP-004: respond_directly mutates member output_schema

**Codex claim:** `_default_tools.py:374` — sets `member.output_schema = None`, permanently clearing it.
**Actual behavior:** Code only ADDS a schema if the member doesn't have one; it doesn't clear existing schemas. Codex misread the code flow.
**Verdict:** False positive.

### FP-005: SqliteDb.close() doesn't clear scoped sessions

**Codex claim:** `sqlite.py:180` — stale thread-local sessions after close.
**Actual behavior:** `db_engine.dispose()` invalidates all connections in the pool. Scoped sessions can't do anything with a disposed engine. `Session.remove()` would be belt-and-suspenders but isn't needed for correctness.
**Verdict:** Not a functional bug.

### FP-006: Step _retry_count vs retry_count field mismatch

**Codex claim:** `step.py:75` — `_retry_count` never updated, `retry_count` written to wrong field.
**Actual behavior:** Neither field is read anywhere. `_retry_count` is dead code. `self.retry_count` creates a dynamic attribute that's also never read. The docstring example in `condition.py:63` references `session_state.retry_count` which is a different thing entirely.
**Verdict:** Dead code, not a bug.

### FP-007: Agent ThreadPoolExecutor leak

**Codex claim:** `agent.py:659` — executor created with no shutdown path.
**Actual behavior:** Executor is a property on the agent instance. When agent is garbage collected, Python's `ThreadPoolExecutor.__del__` shuts down threads. Only matters if creating thousands of agents without GC in a tight loop.
**Verdict:** Theoretical, not practical.

### FP-008: Tavily `include_answer` still passed to `client.search()`

**Codex claim:** `include_answer` is deprecated and shouldn't be passed to Tavily API.
**Actual behavior:** PR #5755 only removed `include_answer` from `get_search_context()` / `web_search_with_tavily()`. The `client.search()` method still accepts it. Verified by reading PR #5755 diff (1-line change, only `web_search_with_tavily`).
**Verdict:** Not a bug.

### FP-009: InMemoryDb race conditions in concurrent access

**Agent claim:** `InMemoryDb` (various methods) has race conditions when accessed from multiple threads — no locks around dict mutations.
**Actual behavior:** `InMemoryDb` is explicitly designed for development and testing only (the class docstring says "In-memory storage for development"). Production deployments use `PostgresDb` or `SqliteDb` which have proper transaction isolation via SQLAlchemy.
**Verdict:** By design. Not a production bug.

### FP-010: Missing raise_for_status in telemetry API calls

**Agent claim:** `api/agent.py`, `api/team.py`, `api/workflow.py` — HTTP POST calls don't check response status codes.
**Actual behavior:** These are fire-and-forget telemetry calls wrapped in bare `except Exception` handlers (e.g., `api/workflow.py:22-28`). Failures are intentionally silenced — telemetry should never crash the user's application. The `api.AsyncClient` is a thin wrapper; adding `raise_for_status` would cause framework crashes when the telemetry server is down.
**Verdict:** Intentional design. Not a bug.

### FP-011: AgentRunException handling masks original exception

**Agent claim:** Various `except AgentRunException` handlers re-raise without full traceback context.
**Actual behavior:** `AgentRunException` is the framework's intentional control flow mechanism — it carries a user-facing message and is caught by the run loop to return as a response. It's not an unexpected error that needs traceback preservation. The `raise` re-raises with full traceback intact (Python default behavior for bare `raise`).
**Verdict:** Working as designed.

### FP-012: MongoDB async_name_exists await precedence (BUG-012 retracted)

**Original claim:** `mongodb.py:1248` — `await collection.find_one(...) is not None` has operator precedence bug; `is not` evaluates before `await`, causing `await True` → TypeError.
**Actual behavior:** Python AST confirms `await` has HIGHER precedence than `is not` (comparison operators). The expression parses as `(await collection.find_one(...)) is not None`, which is correct. Verified with `ast.parse()` — the AST shows `Compare(left=Await(value=Call(...)), ...)`.
**Verdict:** Not a bug. The `await` operator binds to the `primary` (call expression) before the comparison is applied.

### FP-013: MySQL AttributeError before ValueError on invalid config (retracted by Codex)

**Codex claim:** `mysql.py:90-91` — `str(db_engine.url)` triggers AttributeError before ValueError guard.
**Actual behavior:** Due to ternary precedence (BUG-016), the expression parses as `(db_url or str(db_engine.url)) if db_engine else "..."`. When `db_engine=None`, the else branch runs directly — `str(db_engine.url)` is never evaluated. No AttributeError occurs. The ternary precedence is still a bug (BUG-016) but the crash path Codex described doesn't exist.
**Verdict:** Incorrect analysis of precedence. The real bug is BUG-016 (ID collision), not this crash.

### FP-014: ModelResponse.tool_executions Optional but default_factory=list

**Agent claim:** `response.py:120` — `tool_executions: Optional[List[ToolExecution]]` initialized with `field(default_factory=list)` means it's never None, making the Optional misleading.
**Actual behavior:** This is a type annotation style choice, not a functional bug. The `default_factory=list` means callers don't need to pass `tool_executions=[]` explicitly. Code that checks `if self.tool_executions is not None` works correctly (list is not None). The Optional is technically redundant but harmless — common pattern in Pydantic/dataclass codebases.
**Verdict:** Code style, not a bug.

### FP-015: SQL injection in DuckDB/CSV LLM tools

**Agent claim:** `duckdb.py:370`, `csv_toolkit.py:154` — f-string interpolation of `table`, `search_text`, `csv_name` into SQL queries is SQL injection.
**Actual behavior:** These are LLM tools that already expose a `run_query(sql)` method for arbitrary SQL execution by design. The LLM can already run any SQL it wants. The f-string interpolation in helper methods (`full_text_search`, `export_table_to_path`) doesn't add attack surface. Additionally, `csv_toolkit.py` validates `csv_name` against `self.csvs` (line 137) before using it. The security boundary is between the user and the LLM, not between the LLM and the database.
**Verdict:** By design for LLM tool framework. Not a security vulnerability.

### FP-016: Groq http_client `is not None` vs truthiness check inconsistency

**Agent claim:** `groq.py:109` uses `is not None` while `groq.py:134` uses truthiness check — sync/async parity issue.
**Actual behavior:** `http_client` is always either None or an httpx.Client/AsyncClient object. Neither httpx client type has a falsy `__bool__` — they're always truthy when not None. The behavioral difference between `is not None` and truthiness is zero for these types. Cosmetic inconsistency only.
**Verdict:** Code style, not functional.

---

## Audit Metadata

| Metric | Value |
|--------|-------|
| Reviewed by | Codex GPT-5.3 + Opus 4.6 cross-validation |
| Audit rounds | R1 (workflow) + R2 (hooks/guardrails/knowledge/tools) + R3 (knowledge isolation) + R4 (memory/vectordb/workflow/API/reasoning/DB) + R5 (agent/team/models/tools/scheduler/session/OpenAI) + R6 (agent core/team core/models/tools/embedder) + R7 (reproduction testing) + R8 (knowledge readers/chunking/run/learn/utils) + R9 (AgentOS/agent-run/team-run/approval/eval/tracing) |
| Modules audited | workflow, knowledge, agent hooks, team hooks, guardrails, PII, tools (MCP/browserbase/tavily/API/duckdb/csv/shell/python/file), DB migrations, memory, vectordb (mongodb/weaviate/redis/langchain/llamaindex/lightrag), API telemetry, reasoning, DB (sqlite/mysql/singlestore), culture, team delegation tools, models (watsonx/gemini/mistral/litellm/openai-responses/openai-chat/anthropic/aws/azure/cohere/groq/together/deepseek), compression, scheduler, session, agent core, team core, embedder, storage, knowledge readers, knowledge chunking, AgentOS (os/app + routers + interfaces), agent execution (_run.py), team execution (_run.py), approval, eval, tracing |
| Confirmed bugs | 32 (BUG-001 through BUG-033, excluding retracted BUG-012) |
| Bugs reproduced | 15 (R7: BUG-011/013/015/016/017/019/020, R9: BUG-026/027/028/029/030/031/032/033) — all confirmed with running tests |
| Reproduction tests | 48 tests across 8 files in `tests/unit/` — all passing |
| Bugs fixed (other branch) | 5 (FIXED-001 through FIXED-005 on fix/hooks-guardrails) |
| Bugs fixed (knowledge isolation) | 5 (BUG-006 through BUG-010, PR #6482) |
| Suspected issues | 14 |
| Cookbook bugs | 2 |
| False positives | 16 |
| Quality issues (not bugs) | 4 (see REVIEW_LOG.md in each cookbook) |