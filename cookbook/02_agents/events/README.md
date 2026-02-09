# events

Examples for reading and reacting to agent run events.

## Files
- `basic_agent_events.py` - Demonstrates basic agent events.
- `reasoning_agent_events.py` - Demonstrates reasoning agent events.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
