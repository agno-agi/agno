# 10_human_in_the_loop

Examples for confirmation flows, user input prompts, and external tool handling.

## Files
- `agentic_user_input.py` - Agent requests user input during execution.
- `confirmation_advanced.py` - Advanced confirmation patterns.
- `confirmation_required.py` - Require confirmation before tool execution.
- `confirmation_required_mcp_toolkit.py` - Confirmation with MCP toolkit.
- `confirmation_toolkit.py` - Confirmation using a toolkit.
- `external_tool_execution.py` - External tool execution flow.
- `mixed_external_and_regular_tools.py` - Mixed external and regular tools in a single agent.
- `side_effect_tool_approval.py` - Credential-free approval and rejection paths for a simulated side-effecting tool.
- `user_input_required.py` - Tools that require user input.
- `confirmation_with_session_state.py` - Confirmation flow where the tool modifies session_state before pausing. Verifies that state changes survive the pause/continue round-trip.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.
- `side_effect_tool_approval.py` is fully local and needs no API key, credentials, or network access.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/10_human_in_the_loop/<file>.py`

For `side_effect_tool_approval.py`, the application records the authenticated
actor, decision, tool arguments, and timestamp before calling `continue_run()`.
SQLite stores the paused Agent run, while an in-memory list stands in for the
application's approval audit log. Production applications should replace that
list with durable database or audit-log storage.
