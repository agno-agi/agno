# Volcengine Ark

[Volcengine Ark (火山引擎方舟)](https://www.volcengine.com/product/ark) provides large language models (such as the Doubao family) via an
[OpenAI-compatible API](https://www.volcengine.com/docs/82379/), so you can drive them through Agno the same way you'd drive any OpenAI-compatible
provider. The Agno `Ark` class defaults to `doubao-seed-2-1-pro-260628` and points at
`https://ark.cn-beijing.volces.com/api/v3`.

## Thinking mode

Control thinking mode with the `use_thinking` flag:

- `use_thinking=None` (default): the flag is not sent, so the API uses the model default.
- `use_thinking=True`: force thinking on; the model returns `reasoning_content`.
- `use_thinking=False`: force thinking off for a faster, cheaper response.

```python
Ark(id="doubao-seed-2-1-pro-260628", use_thinking=True)
```

You can also adjust reasoning effort using `reasoning_effort` ("minimal", "low", "medium", "high"). Note that sending `reasoning_effort` with `use_thinking=False` is rejected by the API, so `Ark` automatically strips `reasoning_effort` when thinking is disabled.

## Structured output

Volcengine Ark supports native `json_schema` structured outputs with `strict: True`. You can pass a Pydantic model directly to `output_schema`.

## Get an API key

1. Sign in to the [Volcengine Ark Console](https://console.volcengine.com/ark/region:cn-beijing/apiKey).
2. Create an API Key under **API Key Management**.
3. Export your key:

```shell
export ARK_API_KEY=***
```

### 1. Create and activate a virtual environment

See the repository [Development setup](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#development-setup).

### 2. Install libraries

```shell
uv pip install -U openai ddgs agno
```

## Examples

```shell
# Basic agent (sync, async, streaming)
.venvs/demo/bin/python cookbook/90_models/volcengine/basic.py

# Create an agent from the "volcengine:<model-id>" string shorthand
.venvs/demo/bin/python cookbook/90_models/volcengine/string_model.py

# Structured output: return a typed Pydantic object via native json_schema
.venvs/demo/bin/python cookbook/90_models/volcengine/structured_output.py

# Reasoning agent: solve a logic puzzle with thinking mode on
.venvs/demo/bin/python cookbook/90_models/volcengine/reasoning_agent.py

# Toggle thinking mode on/off with the use_thinking flag
.venvs/demo/bin/python cookbook/90_models/volcengine/thinking_mode.py

# Tool use: web search while thinking
.venvs/demo/bin/python cookbook/90_models/volcengine/tool_use.py
```
