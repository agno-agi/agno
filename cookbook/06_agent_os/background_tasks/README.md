# Background Tasks in AgentOS

This directory contains examples demonstrating how to run hooks as background tasks in AgentOS. Background hooks execute after the API response is sent to the user, making them non-blocking.

## Why Use Background Hooks?

Background hooks are useful when you need to perform operations that:
- Don't affect the response to the user
- Can tolerate eventual execution
- Would otherwise add latency to the API response

Common use cases:
- Logging and analytics
- Sending notifications
- Quality evaluation and monitoring
- Storing metrics to a database
- Triggering downstream workflows

## Two Approaches

### 1. Global Setting (`run_hooks_in_background`)

Enable background execution for all hooks at the AgentOS level:

```python
agent_os = AgentOS(
    agents=[agent],
    run_hooks_in_background=True,  # All hooks run in background
)
```

See: `background_hooks_example.py`

### 2. Per-Hook Decorator (`@hook`)

Control background execution per hook using the decorator:

```python
from agno.hooks.decorator import hook

@hook(run_in_background=True)
async def my_background_hook(run_output, agent):
    # This runs in background regardless of global setting
    await send_notification(run_output)

async def my_blocking_hook(run_output, agent):
    # This runs normally (blocking)
    validate_output(run_output)
```

See: `background_hooks_decorator.py`

## Examples

| File | Description |
|------|-------------|
| `background_hooks_example.py` | Basic example using global `run_hooks_in_background=True` |
| `background_hooks_decorator.py` | Per-hook control using `@hook(run_in_background=True)` |
| `background_hooks_team.py` | Background hooks with a Team |
| `background_hooks_workflow.py` | Background hooks with a Workflow |
| `background_output_evaluation.py` | Agent-as-judge pattern for quality monitoring |

## Running the Examples

Start any example server:

```bash
python background_hooks_example.py
```

Test with a request:

```bash
curl -X POST http://localhost:7777/agents/{agent-id}/runs \
  -F "message=Hello!" \
  -F "stream=false"
```

The response returns immediately while background hooks continue executing.

## Background Output Evaluation

The `background_output_evaluation.py` example demonstrates using an evaluator agent to assess response quality without blocking:

```python
@hook(run_in_background=True)
async def evaluate_output_quality(run_output: RunOutput, agent: Agent) -> None:
    result = await evaluator_agent.arun(input=f"Evaluate: {run_output.content}")
    # Log results for monitoring
```

This pattern is useful for:
- Production quality monitoring
- A/B testing response quality
- Compliance auditing
- Building evaluation datasets

## Important Notes

1. **Pre-hooks in background mode cannot modify `run_input`** - modifications won't affect the agent run since it may have already started.

2. **Background hooks cannot block responses** - use blocking hooks if you need to validate/reject outputs.

3. **Error handling** - background hook errors are logged but don't affect the API response.

4. **Agent reuse** - create evaluator agents outside hooks to avoid recreation overhead on every request.

