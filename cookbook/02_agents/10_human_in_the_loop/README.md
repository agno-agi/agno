# 10_human_in_the_loop

Examples for confirmation flows, user input prompts, and external tool handling.

## Files
- `agentic_user_input.py` - Agent requests user input during execution.
- `confirmation_advanced.py` - Advanced confirmation patterns.
- `confirmation_required.py` - Require confirmation before tool execution.
- `confirmation_required_mcp_toolkit.py` - Confirmation with MCP toolkit.
- `confirmation_toolkit.py` - Confirmation using a toolkit.
- `external_tool_execution.py` - External tool execution flow.
- `user_input_required.py` - Tools that require user input.
- `confirmation_with_session_state.py` - Confirmation flow where the tool modifies session_state before pausing. Verifies that state changes survive the pause/continue round-trip.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/10_human_in_the_loop/<file>.py`
