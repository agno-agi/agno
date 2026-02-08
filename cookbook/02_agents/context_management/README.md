# context_management

Examples for instructions, dynamic context, and few-shot behavior shaping.

## Files
- `few_shot_learning.py` - Demonstrates few shot learning.
- `filter_tool_calls_from_history.py` - Demonstrates filter tool calls from history.
- `instructions.py` - Demonstrates instructions.
- `instructions_with_state.py` - Demonstrates instructions with state.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
