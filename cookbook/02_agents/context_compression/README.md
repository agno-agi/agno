# context_compression

Examples for compressing and monitoring tool-call context.

## Files
- `advanced_compression.py` - Demonstrates advanced compression.
- `compression_events.py` - Demonstrates compression events.
- `tool_call_compression.py` - Demonstrates tool call compression.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
