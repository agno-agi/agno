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

# Pretty CLI output: streams spawn panels live and renders the trail at the end.
workflow.print_response(input="...", stream=True, stream_events=True)

# Or get the result object programmatically:
result = workflow.run(input="...")
print(result.content)
for s in result.executed_steps:
    print(s.role, s.output_content[:80])
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
- `06_streaming_events.py` - Live event stream: spawn signals, step lifecycle, agent run
  events, and per-token content from spawned agents.
- `07_code_review.py` - Claude-Code-style agentic code review. Driver spawns specialists
  with `Workspace` (read/edit/write/search files under a sandboxed root) and `ExaTools`
  (web search) to audit a Python class, leave in-file `# AUDIT:` comments, and write a
  Markdown report with concrete fix recommendations.

## v0 limitations

- **HITL.** Pausing inside a spawn is not supported in v0.
- **No recursive spawning.** Spawned agents cannot themselves spawn.

## Prerequisites

- Activate the demo environment: `.venvs/demo/bin/python`
- Load API keys with `direnv allow` (requires a local `.envrc` file).
- For `05_db_persistence.py`: a local Postgres at `postgresql+psycopg://ai:ai@localhost:5532/ai`
  (start one with `./cookbook/scripts/run_pgvector.sh`).
