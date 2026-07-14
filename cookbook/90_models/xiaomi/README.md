# Xiaomi MiMo

[Xiaomi MiMo](https://platform.xiaomimimo.com/) exposes its models through an
[OpenAI-compatible API](https://platform.xiaomimimo.com/docs/en-US/api/chat/openai-api),
so you can drive them through Agno the same way you'd drive any OpenAI-compatible
provider. The Agno `MiMo` class defaults to `mimo-v2.5-pro` and points at
`https://api.xiaomimimo.com/v1`.

## Thinking mode

Control thinking mode with the `use_thinking` flag:

- `use_thinking=None` (default): the flag is not sent, so the API uses the model default.
- `use_thinking=True`: force thinking on; the model returns `reasoning_content`.
- `use_thinking=False`: force thinking off for a faster, cheaper response.

```python
MiMo(id="mimo-v2.5-pro", use_thinking=True)
```

## Get an API key

Sign in with a Xiaomi account (register at [id.mi.com](https://id.mi.com) if you
don't have one), then create a key in the
[console](https://platform.xiaomimimo.com/) under **API Keys**. See the
[quick-start guide](https://platform.xiaomimimo.com/docs/en-US/quick-start/first-api-call)
for a first request.

### 1. Create and activate a virtual environment

See the repository [Development setup](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#development-setup).

### 2. Export your API key

```shell
export MIMO_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

## Examples

```shell
# Basic agent (sync, async, streaming)
.venvs/demo/bin/python cookbook/90_models/xiaomi/basic.py

# Create an agent from the "xiaomi:<model-id>" string shorthand
.venvs/demo/bin/python cookbook/90_models/xiaomi/string_model.py

# Structured output: return a typed Pydantic object via JSON mode
.venvs/demo/bin/python cookbook/90_models/xiaomi/structured_output.py

# Reasoning agent: solve a logic puzzle with thinking mode on
.venvs/demo/bin/python cookbook/90_models/xiaomi/reasoning_agent.py

# Toggle thinking mode on/off with the use_thinking flag
.venvs/demo/bin/python cookbook/90_models/xiaomi/thinking_mode.py

# Tool use: web search while thinking
.venvs/demo/bin/python cookbook/90_models/xiaomi/tool_use.py
```
