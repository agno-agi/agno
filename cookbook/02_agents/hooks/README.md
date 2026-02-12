# hooks

Examples for pre-hooks, post-hooks, and stream lifecycle hooks.

## Files
- `post_hook_output.py` - Demonstrates post hook output.
- `pre_hook_input.py` - Demonstrates pre hook input.
- `session_state_hooks.py` - Demonstrates session state hooks.
- `stream_hook.py` - Demonstrates stream hook.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
