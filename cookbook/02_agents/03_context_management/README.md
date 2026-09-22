# 03_context_management

Examples for instructions, system messages, introduction messages, and context shaping.

## Files
- `few_shot_learning.py` - Demonstrates few-shot learning with example messages.
- `filter_tool_calls_from_history.py` - Filter tool calls from conversation history.
- `instructions.py` - Set agent instructions.
- `instructions_with_state.py` - Dynamic instructions using session state.
- `introduction_message.py` - Set an initial greeting message for the agent.
- `system_message.py` - Customize the agent's system message and role.
- `datetime_format.py` - Customize the datetime format injected into agent context.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/03_context_management/<file>.py`

## Inspect a model request

`prepare_model_request.py` demonstrates synchronous and asynchronous inspection
for both `Agent` and `Team`. It uses an offline model, so it needs no API keys.

```bash
uv run --no-project --python .venvs/demo/bin/python cookbook/02_agents/03_context_management/prepare_model_request.py
```

`prepare_model_request()` and `aprepare_model_request()` return messages, tool
schemas, the response format, run context, and session before model generation.
Preparation still validates input, loads the session, resolves dependencies,
runs pre-hooks, and builds tools and context. Those steps can perform I/O and
mutate in-memory state. No reasoning, background memory/learning, or run
persistence occurs. Tool connections are released before returning; the result
is for inspection, not execution or a provider-specific HTTP payload. Task-mode
teams are not supported. Passing a `background_tasks` collector is rejected;
pre-hooks run inline during inspection.
