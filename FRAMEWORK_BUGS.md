# Framework Bug Tracker

Bugs found during v2.5 cookbook testing & code audit.
Source-verified against `cookbooks/v2.5-testing` branch (2026-02-11).

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

---

### BUG-004: Image artifact UTF-8 decode fails on raw PNG bytes

**Severity:** MEDIUM — silent image data loss
**Location:** `libs/agno/agno/workflow/step.py:1585-1606`
**Since:** v2.5.0
**Status:** Open

**Description:**
`_convert_image_artifacts_to_images` assumes all `bytes` content in `ImageArtifact` is base64-encoded text. When the content is raw image bytes (e.g., PNG starting with `\x89PNG`), the `decode("utf-8")` at line 1587 throws `UnicodeDecodeError`. The exception is caught at line 1603, and the image is silently skipped.

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

---

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

---

## Audit Metadata

| Metric | Value |
|--------|-------|
| Reviewed by | Codex GPT-5.3 + Opus 4.6 cross-validation |
| Cookbooks audited | `00_quickstart/`, `01_demo/`, `04_parallel_execution/`, `05_conditional_branching/`, `06_advanced_concepts/`, `07_cel_expressions/` |
| Total Codex findings | 13 (round 1) + 12 (round 2) |
| Confirmed bugs | 4 |
| Suspected issues | 2 |
| Cookbook bugs | 1 |
| False positives | 7 |
| Quality issues (not bugs) | 4 (see REVIEW_LOG.md in each cookbook) |
