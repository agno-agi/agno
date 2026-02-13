# 03_context_management

Examples for instructions, system messages, introduction messages, and context shaping.

## Files
- `few_shot_learning.py` - Demonstrates few-shot learning with example messages.
- `filter_tool_calls_from_history.py` - Filter tool calls from conversation history.
- `instructions.py` - Set agent instructions.
- `instructions_with_state.py` - Dynamic instructions using session state.
- `introduction_message.py` - Set an initial greeting message for the agent.
- `system_message.py` - Customize the agent's system message and role.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/03_context_management/<file>.py`
