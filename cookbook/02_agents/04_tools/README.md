# 04_tools

Examples for callable tool factories, tool choice, and tool call limits.

## Files
- `01_callable_tools.py` - Vary the toolset per user role using callable factories.
- `02_session_state_tools.py` - Use session_state directly as a parameter with caching disabled.
- `03_team_callable_members.py` - Assemble team members dynamically.
- `04_tools_with_literal_type_param.py` - Use typing.Literal for tool parameters with predefined values.
- `05_same_run_tool_loading.py` - Load a tool on demand and use it in the same Agent run.
- `tool_call_limit.py` - Limit the number of tool calls per run.
- `tool_choice.py` - Control which tool the agent selects.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/04_tools/<file>.py`

## Same-run registration

`05_same_run_tool_loading.py` shows a loader registering a tool during a run and using it on the next model iteration. The new tool is added to the Agent configuration for later runs and continuations; runs that already prepared their tools keep their existing set. If another active run tries to add the same new name after preparation, registration fails before changing either run or the Agent configuration. A name already present in the current run is a no-op, so a run-local or native tool is not shadowed in persistent configuration.

The current run's system prompt and toolkit instructions are not rebuilt, and a newly added MCP tool is not connected automatically. This does not support `add_tool()` when `tools` is a callable factory; configure stable tools with `set_tools()` before the run. Keep configuration available across pause/resume: dynamically created callables are not reconstructed in a fresh process. This behavior does not promise general thread safety for arbitrary concurrent changes to a shared Agent configuration.
