# run_control

Examples for retries, cancellation, serialization, limits, and execution controls.

## Files
- `agent_serialization.py` - Demonstrates agent serialization.
- `cancel_run.py` - Demonstrates cancel run.
- `concurrent_execution.py` - Demonstrates concurrent execution.
- `debug.py` - Demonstrates debug.
- `metrics.py` - Demonstrates metrics.
- `retries.py` - Demonstrates retries.
- `tool_call_limit.py` - Demonstrates tool call limit.
- `tool_choice.py` - Demonstrates tool choice.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
