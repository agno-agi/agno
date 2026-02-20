# 04_tools

Examples for callable tool factories, tool choice, and tool call limits.

## Files
- `01_callable_tools.py` - Vary the toolset per user role using callable factories.
- `02_session_state_tools.py` - Use session_state directly as a parameter with caching disabled.
- `03_team_callable_members.py` - Assemble team members dynamically.
- `tool_call_limit.py` - Limit the number of tool calls per run.
- `tool_choice.py` - Control which tool the agent selects.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/04_tools/<file>.py`
