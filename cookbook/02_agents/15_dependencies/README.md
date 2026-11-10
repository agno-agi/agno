# dependencies

Examples for runtime dependency injection and dynamic runtime inputs.

## Files
- `dependencies_in_context.py` - Demonstrates dependencies in context.
- `dependencies_in_tools.py` - Demonstrates dependencies in tools.
- `dynamic_tools.py` - Demonstrates dynamic tools.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
