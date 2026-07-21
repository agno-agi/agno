# DeepSeek Cookbook

[DeepSeek](https://api-docs.deepseek.com/) provides an OpenAI-compatible API. Agno's
`DeepSeek` model defaults to `deepseek-v4-flash`.

## Models

| Model id | Description |
|---|---|
| `deepseek-v4-flash` | Fast V4 model (default), 1M context. Hybrid: thinking + non-thinking. |
| `deepseek-v4-pro` | Flagship V4 model, 1M context. Hybrid: thinking + non-thinking. |

Thinking mode is **enabled by default** for V4 models, so the model returns
`reasoning_content` out of the box. Control it with the `use_thinking` flag:
`DeepSeek(id="deepseek-v4-flash", use_thinking=False)` turns it off,
`use_thinking=True` forces it on.

For demanding agent tasks, set `reasoning_effort="max"` (valid values: `high`, `max`).
While thinking mode is active, `temperature`, `top_p`, `presence_penalty` and
`frequency_penalty` are ignored by the API.

### Deprecated model ids

The legacy ids still work and route server-side, but you should migrate:

| Legacy id | Maps to |
|---|---|
| `deepseek-chat` | non-thinking mode of `deepseek-v4-flash` |
| `deepseek-reasoner` | thinking mode of `deepseek-v4-flash` |

## Setup

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `DEEPSEEK_API_KEY`

```shell
export DEEPSEEK_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs duckdb yfinance agno
```

## Examples

```shell
# Basic agent (sync, async, streaming)
python cookbook/90_models/deepseek/basic.py

# Tool use
python cookbook/90_models/deepseek/tool_use.py

# Structured output
python cookbook/90_models/deepseek/structured_output.py

# Reasoning agent (thinking mode)
python cookbook/90_models/deepseek/reasoning_agent.py

# Thinking + tool calls
python cookbook/90_models/deepseek/thinking_tool_calls.py

# Controlling reasoning effort
python cookbook/90_models/deepseek/reasoning_effort.py

# Toggling thinking mode on/off
python cookbook/90_models/deepseek/thinking_mode.py

# Retry behavior
python cookbook/90_models/deepseek/retry.py
```
