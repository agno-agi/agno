# 04_workflows/09_dynamic_workflows

Dynamic Workflows let a workflow **expand itself at runtime**. Instead of declaring a
static list of steps, you hand the workflow a `DynamicWorkflowDriver`. The driver invents
new specialist agents on demand (role, instructions, tools, optional model tier), runs
them, sees the result, and decides the next spawn — until the goal is met.

This is the workflow-level mirror of the dynamic-subagents pattern: a `spawn_agent` tool
that creates and runs an ephemeral agent, then returns a short summary back to the driver
so its context stays clean across many spawns.

## DX

```python
from agno.workflow import DynamicWorkflowDriver, Workflow

driver = DynamicWorkflowDriver(model=..., instructions=..., allowed_tools=[...])
workflow = Workflow(name="...", steps=driver)

result = workflow.run(input="...")
result.pretty_print_plan()             # the steps the driver actually ran
```

The driver populates two artifacts on the run output:
- `executed_steps`: ordered list of `ExecutedStepRecord` (iteration, role, instructions,
  input, output preview, tools, model tier) — the canonical "what the workflow did" trail.
- `step_results`: same trail re-expressed as `StepOutput` for compatibility with the rest
  of the workflow ecosystem.

## Files

- `01_basic.py` - Minimal LLM-driven setup: model, instructions, allowed_tools, max_steps.
- `02_custom_driver.py` - Python-driven mode via `custom_driver=` for deterministic dispatch.
- `03_model_tiers.py` - Cost-aware per-spawn model selection via `model_tiers` + tier hints.
- `04_tool_whitelist.py` - `allowed_tools` + `allow_tool_selection` for per-spawn tool subsets.
- `05_db_persistence.py` - Persist runs to Postgres and reload the `executed_steps` trail.

## v0 limitations

- **Streaming.** `workflow.run(stream=True)` currently emits only `WorkflowStartedEvent` and
  `WorkflowCompletedEvent` for dynamic workflows — no per-spawn events on the stream. The
  full `executed_steps` trail and `StepSpawnedEvent`s are available on the final result.
  Live-stream-of-spawns is a v0.1 follow-up.
- **HITL.** Pausing inside a spawn is not supported in v0.
- **No recursive spawning.** Spawned agents cannot themselves spawn.

## Prerequisites

- Activate the demo environment: `.venvs/demo/bin/python`
- Load API keys with `direnv allow` (requires a local `.envrc` file).
- For `05_db_persistence.py`: a local Postgres at `postgresql+psycopg://ai:ai@localhost:5532/ai`
  (start one with `./cookbook/scripts/run_pgvector.sh`).
