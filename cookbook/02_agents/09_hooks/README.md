# 09_hooks

Examples for pre-hooks, post-hooks, tool hooks, and stream lifecycle hooks.

## Files
- `post_hook_output.py` - Run a hook after the agent responds.
- `pre_hook_input.py` - Run a hook before the agent processes input.
- `session_state_hooks.py` - Hooks that read and modify session state.
- `stream_hook.py` - Hook into the streaming lifecycle.
- `tool_hooks.py` - Middleware hooks that wrap every tool call.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/09_hooks/<file>.py`
