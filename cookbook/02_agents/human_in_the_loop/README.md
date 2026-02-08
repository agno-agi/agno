# human_in_the_loop

Examples for confirmation flows, user input prompts, and external tool handling.

## Files
- `agentic_user_input.py` - Demonstrates agentic user input.
- `confirmation_advanced.py` - Demonstrates confirmation advanced.
- `confirmation_required.py` - Demonstrates confirmation required.
- `confirmation_toolkit.py` - Demonstrates confirmation toolkit.
- `external_tool_execution.py` - Demonstrates external tool execution.
- `user_input_required.py` - Demonstrates user input required.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
