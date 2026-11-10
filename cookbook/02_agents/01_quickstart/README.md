# 01_quickstart

Starter examples for creating and running agents with core settings.

## Files
- `agent_with_instructions.py` - Demonstrates agent with instructions.
- `agent_with_tools.py` - Demonstrates agent with tools.
- `basic_agent.py` - Demonstrates basic agent.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
