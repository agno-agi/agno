# Restructuring Plan: `cookbook/04_workflows/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Main directories | 7 (deeply nested with sync/async subdirs) |
| Total `.py` files (non-`__init__`) | ~126 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~32 (~25%) |
| Have section banners | ~8 (~6%) |
| Have `if __name__` gate | ~113 (~90%) |
| Contain emoji | ~1 (step_with_function.py has checkmarks) |
| Directories with README.md | 1 main + 2 nested |
| Directories with TEST_LOG.md | 0 |

### Key Problems

1. **Systematic sync/async duplication.** Every pattern directory contains separate `sync/` and `async/` subdirectories with mirrored files. The async variants differ only by adding `asyncio.run()`, `await`, and `arun()`. This creates ~30 duplicate files.

2. **Systematic stream/non-stream duplication.** Most patterns have separate `_stream.py` files that only add `stream=True`. This creates ~15 additional duplicates.

3. **Deep nesting.** Files are 4 levels deep: `_01_basic_workflows/_01_sequence_of_steps/sync/sequence_of_steps.py`. This makes paths unwieldy and obscures content.

4. **Poor docstring coverage.** Only ~25% of files have module docstrings (lowest of all cookbook sections).

5. **Catch-all directory.** `_06_advanced_concepts/_10_other/` mixes tools, events, cancellation, metrics, session renaming, and image input.

6. **Numbered variants without clear purpose.** `_01_structured_io/` has `function.py`, `function_1.py`, `function_2.py` — the numbering doesn't explain what's different. Similarly, `_03_access_previous_step_outputs/` has three numbered variants of the same concept.

7. **Almost no documentation.** Only the root README.md exists (comprehensive but single file). No subdirectory has README.md or TEST_LOG.md.

### Overall Assessment

Workflows has the worst redundancy structure of the three sections — the sync/async/stream duplication is architectural (at the directory level rather than file level). However, the content is well-organized conceptually: each directory maps to a clear workflow pattern (sequence, condition, loop, parallel, router). The main restructuring work is flattening the sync/async/stream splits and adding style compliance.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | ~126 | ~72 |
| Max directory depth | 4 levels | 2 levels |
| Style compliance | 0% | 100% |
| README coverage | 1/7 | 7/7 + advanced subdirs |
| TEST_LOG coverage | 0 | All directories |

---

## 2. Proposed Directory Structure

Flatten the `sync/` and `async/` subdirectories. Rename directories to drop leading underscores and verbose prefixes. Keep the numbered progression (it serves as a tutorial path).

```
cookbook/04_workflows/
├── 01_basic_workflows/
│   ├── 01_sequence_of_steps/       # Sequential step execution
│   ├── 02_step_with_function/      # Custom function executors
│   └── 03_function_workflows/      # Pure function workflows (Workflows 1.0 style)
├── 02_conditional_execution/       # Condition evaluators and if/else branching
├── 03_loop_execution/              # Loop with end conditions and max iterations
├── 04_parallel_execution/          # Concurrent step execution
├── 05_conditional_branching/       # Router/selector patterns
├── 06_advanced_concepts/
│   ├── structured_io/              # Pydantic input/output at step/workflow level
│   ├── early_stopping/             # StepOutput(stop=True) patterns
│   ├── previous_step_outputs/      # Accessing previous step data
│   ├── session_state/              # Shared state across steps
│   ├── background_execution/       # Background and WebSocket patterns
│   ├── guardrails/                 # Workflow-level guardrails
│   ├── history/                    # Workflow history and continuous execution
│   ├── workflow_agent/             # WorkflowAgent (agentic orchestration)
│   ├── long_running/               # WebSocket reconnect, replay, catchup
│   ├── run_control/                # [NEW from _10_other] Cancel, metrics, events
│   └── tools/                      # [MOVED from _10_other] Workflow tools
└── 07_cel_expressions/
    ├── condition/                  # CEL in Condition evaluators
    ├── loop/                       # CEL in Loop end conditions
    └── router/                     # CEL in Router selectors
```

### Changes from Current

| Change | Details |
|--------|---------|
| **FLATTEN** `sync/` and `async/` subdirs | All files merge sync+async into one file. No more separate subdirectories |
| **FLATTEN** stream/non-stream pairs | Streaming demonstrated as section within base file |
| **RENAME** all directories | Drop `_` prefix and verbose `_workflows_` in names |
| **DISSOLVE** `_10_other/` | Redistribute: tools→own dir, cancel/metrics/events→run_control, session rename→session_state, image input→structured_io |
| **RENAME** `_06` subdirs | Shorter names, drop `_0N_` prefixes |

---

## 3. File Disposition Table

### Structural Note

The primary change is **eliminating the sync/async/stream directory split**. For each set of 2-4 mirrored files (sync, async, sync_stream, async_stream), the disposition is:
- Base sync file → **REWRITE** (becomes unified file showing sync + async + streaming)
- Async counterpart → **MERGE INTO** base file
- Stream variant → **MERGE INTO** base file
- Async stream variant → **MERGE INTO** base file

---

### `_01_basic_workflows/_01_sequence_of_steps/` (14 files → 6)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `sync/sequence_of_steps.py` + `async/...` + both `_stream` variants | **REWRITE** | `01_basic_workflows/01_sequence_of_steps/sequence_of_steps.py` | Merge 4 files (sync, async, sync_stream, async_stream) into one showing all patterns |
| `sync/sequence_of_functions_and_agents.py` + `async/...` + both `_stream` variants | **REWRITE** | `01_basic_workflows/01_sequence_of_steps/sequence_with_functions.py` | Merge 4 files. Rename for clarity |
| `sync/workflow_using_steps.py` + `async/...` | **REWRITE** | `01_basic_workflows/01_sequence_of_steps/workflow_using_steps.py` | Merge 2 files |
| `sync/workflow_using_steps_nested.py` | **KEEP + FIX** | `01_basic_workflows/01_sequence_of_steps/workflow_using_steps_nested.py` | Unique: nested Steps with Condition and Parallel. Add docstring, banners |
| `sync/workflow_with_file_input.py` | **KEEP + FIX** | `01_basic_workflows/01_sequence_of_steps/workflow_with_file_input.py` | Unique: file-based input. Add docstring, banners |
| `sync/workflow_with_session_metrics.py` | **KEEP + FIX** | `01_basic_workflows/01_sequence_of_steps/workflow_with_session_metrics.py` | Unique: session metrics. Add docstring, banners |
| `async/run_with_arun_stream.py` | **MERGE INTO** `sequence_of_steps.py` | — | Advanced async streaming — add as section in the main sequence file |

---

### `_01_basic_workflows/_02_step_with_function/` (7 files → 3)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `sync/step_with_function.py` + `async/step_with_function_stream.py` + `sync/step_with_function_stream.py` | **REWRITE** | `01_basic_workflows/02_step_with_function/step_with_function.py` | Merge 3 files. Note: no direct async base counterpart exists, but async stream covers it |
| `sync/step_with_function_additional_data.py` + `async/...` | **REWRITE** | `01_basic_workflows/02_step_with_function/step_with_additional_data.py` | Merge 2 files. Shorten name |
| `sync/step_with_class.py` + `async/step_with_async_class.py` | **REWRITE** | `01_basic_workflows/02_step_with_function/step_with_class.py` | Merge 2 files. Show sync class + async class in one file |

---

### `_01_basic_workflows/_03_function_instead_of_steps/` (4 files → 1)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `sync/function_instead_of_steps.py` + `async/...` + both `_stream` variants | **REWRITE** | `01_basic_workflows/03_function_workflows/function_workflow.py` | Merge all 4 files. Single concept (pure function as workflow) shown with all execution modes |

---

### `_02_workflows_conditional_execution/` (10 files → 4)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `sync/condition_steps_workflow_stream.py` + `async/...` | **REWRITE** | `02_conditional_execution/condition_basic.py` | Merge sync+async. Rename: this is the basic condition example |
| `sync/condition_with_list_of_steps.py` + `async/...` | **REWRITE** | `02_conditional_execution/condition_with_list.py` | Merge sync+async. Shorten name |
| `sync/condition_with_else_steps.py` + `async/...` | **REWRITE** | `02_conditional_execution/condition_with_else.py` | Merge sync+async. Shorten name |
| `sync/condition_and_parallel_steps.py` + `async/...` + both `_stream` variants | **REWRITE** | `02_conditional_execution/condition_with_parallel.py` | Merge 4 files (sync, async, sync_stream, async_stream). Shorten name |

---

### `_03_workflows_loop_execution/` (7 files → 2)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `sync/loop_steps_workflow.py` + `async/...` + both `_stream` variants | **REWRITE** | `03_loop_execution/loop_basic.py` | Merge 4 files. Rename for clarity |
| `sync/loop_with_parallel_steps.py` + `sync/..._stream` + `async/..._stream` | **REWRITE** | `03_loop_execution/loop_with_parallel.py` | Merge 3 files. Shorten name |

---

### `_04_workflows_parallel_execution/` (6 files → 2)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `sync/parallel_steps_workflow.py` + `async/...` + both `_stream` variants | **REWRITE** | `04_parallel_execution/parallel_basic.py` | Merge 4 files. Rename for clarity |
| `sync/parallel_and_condition_steps_stream.py` + `async/...` | **REWRITE** | `04_parallel_execution/parallel_with_condition.py` | Merge 2 files. Shorten name |

---

### `_05_workflows_conditional_branching/` (13 files → 7)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `sync/01_string_selector.py` | **KEEP + RENAME + FIX** | `05_conditional_branching/string_selector.py` | Unique: string-based selector. Drop number prefix. Add banners |
| `sync/02_step_choices_parameter.py` | **KEEP + RENAME + FIX** | `05_conditional_branching/step_choices_parameter.py` | Unique: step_choices access. Drop number prefix. Add banners |
| `sync/03_nested_choices.py` | **KEEP + RENAME + FIX** | `05_conditional_branching/nested_choices.py` | Unique: hierarchical choices. Drop number prefix. Add banners |
| `sync/04_loop_in_choices.py` | **KEEP + RENAME + FIX** | `05_conditional_branching/loop_in_choices.py` | Unique: loop as router choice. Drop number prefix. Add banners |
| `sync/router_steps_workflow.py` + `async/...` + both `_stream` variants | **REWRITE** | `05_conditional_branching/router_basic.py` | Merge 4 files. Rename for clarity |
| `sync/router_with_loop_steps.py` + `async/...` | **REWRITE** | `05_conditional_branching/router_with_loop.py` | Merge 2 files. Shorten name |
| `sync/selector_for_image_video_generation_pipelines.py` + `async/...` | **REWRITE** | `05_conditional_branching/selector_media_pipeline.py` | Merge 2 files. Shorten verbose name |
| `sync/selector_types.py` | **KEEP + FIX** | `05_conditional_branching/selector_types.py` | Unique: comprehensive selector return types reference. Already has banners. Add docstring, main gate |

---

### `_06_advanced_concepts/_01_structured_io_at_each_level/` (9 files → 5)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `pydantic_model_as_input.py` | **KEEP + FIX** | `06_advanced_concepts/structured_io/pydantic_input.py` | Unique: Pydantic model as workflow input. Rename. Add docstring, banners |
| `workflow_with_input_schema.py` | **KEEP + FIX** | `06_advanced_concepts/structured_io/input_schema.py` | Unique: input_schema parameter. Rename. Add docstring, banners |
| `structured_io_at_each_level_agent.py` + `..._stream.py` | **REWRITE** | `06_advanced_concepts/structured_io/structured_io_agent.py` | Merge stream variant into base. Shorten name |
| `structured_io_at_each_level_team.py` + `..._stream.py` | **REWRITE** | `06_advanced_concepts/structured_io/structured_io_team.py` | Merge stream variant into base. Shorten name |
| `structured_io_at_each_level_function.py` | **REWRITE** | `06_advanced_concepts/structured_io/structured_io_function.py` | Absorb `_1.py` and `_2.py` variants as sections. The numbered variants lack clear differentiation |
| `structured_io_at_each_level_function_1.py` | **MERGE INTO** `structured_io_function.py` | — | Variant 1 — merge into consolidated function file |
| `structured_io_at_each_level_function_2.py` | **MERGE INTO** `structured_io_function.py` | — | Variant 2 — merge into consolidated function file |

---

### `_06_advanced_concepts/_02_early_stopping/` (7 files → 4)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `early_stop_workflow_with_step.py` | **REWRITE** | `06_advanced_concepts/early_stopping/early_stop_basic.py` | Merge with `..._with_steps.py` and `..._with_agents.py`. Show early stop in basic steps + Steps container + agents |
| `early_stop_workflow_with_steps.py` | **MERGE INTO** `early_stop_basic.py` | — | Steps container variant — closely related to basic step |
| `early_stop_workflow_with_agents.py` | **MERGE INTO** `early_stop_basic.py` | — | Agent variant — same StepOutput(stop=True) mechanism |
| `early_stop_workflow_with_condition.py` | **KEEP + FIX** | `06_advanced_concepts/early_stopping/early_stop_condition.py` | Unique: condition-triggered stop. Rename. Add docstring, banners |
| `early_stop_workflow_with_loop.py` | **KEEP + FIX** | `06_advanced_concepts/early_stopping/early_stop_loop.py` | Unique: stop within loop. Rename. Add docstring, banners |
| `early_stop_workflow_with_parallel.py` | **KEEP + FIX** | `06_advanced_concepts/early_stopping/early_stop_parallel.py` | Unique: stop in parallel context. Rename. Add docstring, banners |
| `early_stop_workflow_with_router.py` | **CUT** | — | Router-based stop is a combination of router + basic stop — not a distinct enough pattern |

---

### `_06_advanced_concepts/_03_access_previous_step_outputs/` (3 files → 1)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `access_multiple_previous_steps_output_stream.py` | **REWRITE** | `06_advanced_concepts/previous_step_outputs/access_previous_outputs.py` | Merge all 3 files. They show variants of the same concept (get_step_content, get_all_previous_content). Shorten name |
| `access_multiple_previous_steps_output_stream_1.py` | **MERGE INTO** above | — | Variant 1 — same concept |
| `access_multiple_previous_step_output_stream_2.py` | **MERGE INTO** above | — | Variant 2 — same concept |

---

### `_06_advanced_concepts/_04_shared_session_state/` (7 files → 5)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `shared_session_state_with_agent.py` | **KEEP + FIX** | `06_advanced_concepts/session_state/state_with_agent.py` | Unique: agent step accessing session_state. Rename. Add docstring, banners |
| `shared_session_state_with_team.py` | **KEEP + FIX** | `06_advanced_concepts/session_state/state_with_team.py` | Unique: team step with session_state. Rename. Add docstring, banners |
| `access_session_state_in_custom_python_function_step.py` + `..._stream.py` | **REWRITE** | `06_advanced_concepts/session_state/state_in_function.py` | Merge stream variant. Shorten name. Add docstring, banners |
| `condition_with_session_state_in_evaluator_function.py` | **KEEP + FIX** | `06_advanced_concepts/session_state/state_in_condition.py` | Unique: evaluator using session_state. Rename. Add banners |
| `router_with_session_state_in_selector_function.py` | **REWRITE** | `06_advanced_concepts/session_state/state_in_router.py` | Absorb `session_state_with_router_workflow.py` (complex router with state). Rename |
| `session_state_with_router_workflow.py` | **MERGE INTO** `state_in_router.py` | — | Complex router variant — same concept as state in router selector |

---

### `_06_advanced_concepts/_05_background_execution/` (3 files → 3, no change)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `background_execution_poll.py` | **KEEP + FIX** | `06_advanced_concepts/background_execution/background_poll.py` | Unique: polling-based background execution. Rename. Add docstring, banners |
| `websocket_server.py` | **KEEP + FIX** | `06_advanced_concepts/background_execution/websocket_server.py` | Unique: WebSocket server. Add docstring, banners |
| `websocket_client.py` | **KEEP + FIX** | `06_advanced_concepts/background_execution/websocket_client.py` | Unique: WebSocket client. Add docstring, banners |

---

### `_06_advanced_concepts/_06_guardrails/` (1 file → 1, no change)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `prompt_injection_workflow.py` | **KEEP + FIX** | `06_advanced_concepts/guardrails/prompt_injection.py` | Unique: workflow guardrails. Rename. Add banners |

---

### `_06_advanced_concepts/_07_workflow_history/` (6 files → 4)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `01_single_step_continuous_execution_workflow.py` | **KEEP + RENAME + FIX** | `06_advanced_concepts/history/continuous_execution.py` | Unique: single-step continuous workflow. Drop prefix. Add docstring |
| `02_workflow_with_history_enabled_for_steps.py` | **REWRITE** | `06_advanced_concepts/history/step_history.py` | Merge with `03_enable_history_for_step.py`. Both show enable_history at different levels |
| `03_enable_history_for_step.py` | **MERGE INTO** `step_history.py` | — | Per-step history — same concept as workflow-level history |
| `04_get_history_in_function.py` | **KEEP + RENAME + FIX** | `06_advanced_concepts/history/history_in_function.py` | Unique: function step accessing history. Drop prefix. Add banners |
| `05_multi_purpose_cli.py` | **CUT** | — | CLI application — not a minimal feature demo. Belongs in examples, not feature cookbooks |
| `06_intent_routing_with_history.py` | **KEEP + RENAME + FIX** | `06_advanced_concepts/history/intent_routing_with_history.py` | Unique: history-based routing. Drop prefix. Add banners |

---

### `_06_advanced_concepts/_08_workflow_agent/` (5 files → 2)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `sync/basic_workflow_agent.py` + `async/...` + both `_stream` variants | **REWRITE** | `06_advanced_concepts/workflow_agent/basic_workflow_agent.py` | Merge 4 files (sync, async, sync_stream, async_stream) into one |
| `async/workflow_agent_and_conditional_step.py` | **KEEP + FIX** | `06_advanced_concepts/workflow_agent/workflow_agent_with_condition.py` | Unique: WorkflowAgent with conditional logic. Rename. Add docstring, banners |

---

### `_06_advanced_concepts/_09_long_running_workflows/` (3 files → 3, no change)

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `01_workflow_websocket_reconnect.py` | **KEEP + RENAME + FIX** | `06_advanced_concepts/long_running/websocket_reconnect.py` | Unique: reconnection with backoff. Drop prefix. Add banners |
| `02_workflow_events_replay.py` | **KEEP + RENAME + FIX** | `06_advanced_concepts/long_running/events_replay.py` | Unique: event-based recovery. Drop prefix. Add banners |
| `03_workflow_disruption_fully_catchup.py` | **KEEP + RENAME + FIX** | `06_advanced_concepts/long_running/disruption_catchup.py` | Unique: interruption handling. Drop prefix. Add banners |

---

### `_06_advanced_concepts/_10_other/` → dissolve

| File(s) | Disposition | New Location | Rationale |
|---------|------------|-------------|-----------|
| `workflow_tools.py` | **KEEP + MOVE + FIX** | `06_advanced_concepts/tools/workflow_tools.py` | Custom tools on workflow steps. Own subdirectory. Add banners, main gate |
| `stream_executor_events.py` | **KEEP + MOVE + FIX** | `06_advanced_concepts/run_control/executor_events.py` | Executor-level event streaming. Move to run_control. Add banners |
| `workflow_cancel_a_run.py` | **KEEP + MOVE + FIX** | `06_advanced_concepts/run_control/cancel_run.py` | Run cancellation. Move to run_control. Rename. Add banners |
| `workflow_metrics_on_run_response.py` | **KEEP + MOVE + FIX** | `06_advanced_concepts/run_control/metrics.py` | Run metrics. Move to run_control. Rename. Add docstring, banners |
| `store_events_and_events_to_skip_in_a_workflow.py` | **KEEP + MOVE + FIX** | `06_advanced_concepts/run_control/event_storage.py` | Event configuration. Move to run_control. Rename. Add docstring, banners, main gate |
| `rename_workflow_session.py` | **MOVE + FIX** | `06_advanced_concepts/session_state/rename_session.py` | Session management — belongs with session_state. Add docstring, banners |
| `workflow_with_image_input.py` | **MOVE + FIX** | `06_advanced_concepts/structured_io/image_input.py` | Media input — belongs with structured I/O. Add docstring, banners |

---

### `_07_cel_expressions/` (14 files → 14, no change)

All CEL expression files are unique — each demonstrates a different CEL pattern/context variable. Keep all.

**`condition/` (5 files)**

| File | Disposition | New Location | Rationale |
|------|------------|-------------|-----------|
| `cel_basic.py` | **KEEP + FIX** | `07_cel_expressions/condition/cel_basic.py` | Unique: `input.contains()`. Add banners |
| `cel_additional_data.py` | **KEEP + FIX** | `07_cel_expressions/condition/cel_additional_data.py` | Unique: `additional_data.priority`. Add banners |
| `cel_session_state.py` | **KEEP + FIX** | `07_cel_expressions/condition/cel_session_state.py` | Unique: `session_state.retry_count`. Add banners |
| `cel_previous_step.py` | **KEEP + FIX** | `07_cel_expressions/condition/cel_previous_step.py` | Unique: `previous_step_content.contains()`. Add banners |
| `cel_previous_step_outputs.py` | **KEEP + FIX** | `07_cel_expressions/condition/cel_previous_step_outputs.py` | Unique: `previous_step_outputs.StepName`. Add banners |

**`loop/` (4 files)**

| File | Disposition | New Location | Rationale |
|------|------------|-------------|-----------|
| `cel_iteration_limit.py` | **KEEP + FIX** | `07_cel_expressions/loop/cel_iteration_limit.py` | Unique: `current_iteration >= N`. Add banners |
| `cel_content_keyword.py` | **KEEP + FIX** | `07_cel_expressions/loop/cel_content_keyword.py` | Unique: `last_step_content.contains()`. Add banners |
| `cel_step_outputs_check.py` | **KEEP + FIX** | `07_cel_expressions/loop/cel_step_outputs_check.py` | Unique: `step_outputs.Step.contains()`. Add banners |
| `cel_compound_exit.py` | **KEEP + FIX** | `07_cel_expressions/loop/cel_compound_exit.py` | Unique: compound boolean conditions. Add banners |

**`router/` (5 files)**

| File | Disposition | New Location | Rationale |
|------|------------|-------------|-----------|
| `cel_ternary.py` | **KEEP + FIX** | `07_cel_expressions/router/cel_ternary.py` | Unique: ternary expressions. Add banners |
| `cel_additional_data_route.py` | **KEEP + FIX** | `07_cel_expressions/router/cel_additional_data_route.py` | Unique: routing via additional_data. Add banners |
| `cel_session_state_route.py` | **KEEP + FIX** | `07_cel_expressions/router/cel_session_state_route.py` | Unique: routing via session_state. Add banners |
| `cel_previous_step_route.py` | **KEEP + FIX** | `07_cel_expressions/router/cel_previous_step_route.py` | Unique: routing via previous output. Add banners |
| `cel_using_step_choices.py` | **KEEP + FIX** | `07_cel_expressions/router/cel_using_step_choices.py` | Unique: step_choices array access. Add banners |

---

## 4. New Files Needed

| Suggested File | Directory | Feature | Description |
|----------------|-----------|---------|-------------|
| `remote_workflow.py` | `06_advanced_concepts/run_control/` | RemoteWorkflow | Demonstrate executing workflows on a remote server via AgentOS or A2A protocol |
| `workflow_serialization.py` | `06_advanced_concepts/run_control/` | save/load/to_dict | Demonstrate workflow persistence, serialization, and deserialization |
| `deep_copy.py` | `06_advanced_concepts/run_control/` | deep_copy() | Demonstrate creating isolated workflow copies with field updates |
| `workflow_cli.py` | `06_advanced_concepts/run_control/` | cli_app() | Demonstrate the built-in CLI interface for workflows (replaces cut 05_multi_purpose_cli.py with a focused version) |

---

## 5. Missing READMEs and TEST_LOGs

| Directory / Subdirectory | README.md | TEST_LOG.md |
|--------------------------|-----------|-------------|
| `04_workflows/` (root) | EXISTS | **MISSING** |
| `_01_basic_workflows/` | **MISSING** | **MISSING** |
| `_01_basic_workflows/_01_sequence_of_steps/` | **MISSING** | **MISSING** |
| `_01_basic_workflows/_02_step_with_function/` | **MISSING** | **MISSING** |
| `_01_basic_workflows/_03_function_instead_of_steps/` | **MISSING** | **MISSING** |
| `_02_workflows_conditional_execution/` | **MISSING** | **MISSING** |
| `_03_workflows_loop_execution/` | **MISSING** | **MISSING** |
| `_04_workflows_parallel_execution/` | **MISSING** | **MISSING** |
| `_05_workflows_conditional_branching/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_01_structured_io/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_02_early_stopping/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_03_access_prev/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_04_shared_session_state/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_05_background_execution/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_05_.../websocket/` | EXISTS | **MISSING** |
| `_06_advanced_concepts/_06_guardrails/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_07_workflow_history/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_08_workflow_agent/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_09_long_running/` | **MISSING** | **MISSING** |
| `_06_advanced_concepts/_10_other/` | **MISSING** | **MISSING** |
| `_07_cel_expressions/` | EXISTS | **MISSING** |

**Summary:** 3 READMEs exist (root, websocket, CEL). 0 TEST_LOGs exist. After restructuring, every directory with runnable `.py` files needs both.

---

## 6. Recommended Cookbook Template

Workflows have unique structure (Step definitions, Workflow wrapping), so the template differs slightly from agents/teams.

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using Agno Workflows.

Key concepts:
- <concept 1>
- <concept 2>
"""

# ============================================================================
# Setup
# ============================================================================

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import Workflow
from agno.workflow.step import Step

# ============================================================================
# Create Agents
# ============================================================================

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["Research the topic thoroughly."],
)

writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["Write a clear summary."],
)

# ============================================================================
# Define Steps
# ============================================================================

research_step = Step(agent=researcher, name="Research")
write_step = Step(agent=writer, name="Write")

# ============================================================================
# Create Workflow
# ============================================================================

workflow = Workflow(
    name="Research Pipeline",
    steps=[research_step, write_step],
)

# ============================================================================
# Run Workflow
# ============================================================================

if __name__ == "__main__":
    # Sync execution
    workflow.print_response("Explain quantum computing", stream=True)

    # Async execution (when demonstrating both patterns)
    # import asyncio
    # asyncio.run(workflow.aprint_response("Explain quantum computing", stream=True))
```

### Template Rules

1. **Module docstring** — Title with `=====` underline, key concepts listed
2. **Section banners** — `# ============================================================================`
3. **Section flow** — Setup → Create Agents/Teams → Define Steps → Create Workflow → Run Workflow
4. **Main gate** — All runnable code inside `if __name__ == "__main__":`
5. **No emoji** — No emoji characters anywhere
6. **Sync + async together** — Show both execution modes in sections
7. **Stream + non-stream together** — Show `stream=True` as default, note non-streaming option

### Best Current Examples (reference)

1. **`_07_cel_expressions/condition/cel_basic.py`** — Good docstring, clear structure, focused on one CEL pattern. Has main gate. Needs: section banners.
2. **`_06_advanced_concepts/_07_workflow_history/01_single_step_continuous_execution_workflow.py`** — Good docstring, has section banners (only file with both!), has main gate. Best overall compliance.
3. **`_05_workflows_conditional_branching/sync/selector_types.py`** — Comprehensive reference with section banners showing all selector patterns. Needs: main gate.
