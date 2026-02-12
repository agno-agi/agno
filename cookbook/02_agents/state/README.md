# state

Examples for reading, updating, and managing session state patterns.

## Files
- `agentic_session_state.py` - Demonstrates agentic session state.
- `dynamic_session_state.py` - Demonstrates dynamic session state.
- `session_state_advanced.py` - Demonstrates session state advanced.
- `session_state_basic.py` - Demonstrates session state basic.
- `session_state_events.py` - Demonstrates session state events.
- `session_state_manual_update.py` - Demonstrates session state manual update.
- `session_state_multiple_users.py` - Demonstrates session state multiple users.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
