# Sarvam AI

[Sarvam AI](https://www.sarvam.ai/) serves its Token Factory models through an
[OpenAI-compatible Chat Completions API](https://docs.sarvam.ai/api/token-factory/chat-completions).
The Agno `Sarvam` class defaults to `sarvam-105b` and points at
`https://api.sarvam.ai/v2`.

## Models

| Model ID | Context | Modalities | Reasoning |
| --- | --- | --- | --- |
| `sarvam-105b` | 128K | Text | `low` (default), `medium`, `high`; off with `none` |
| `sarvam-105b-conversations` | 32K | Text | Off; `reasoning_effort` is ignored |
| `glm5.3` | 1M | Text | `low`, `high`, `max`; always on |
| `glm5.3-flash` | 1M | Text, image | `low`, `high`, `max`; always on |
| `gemma4` | 256K | Text, image | Off by default; `low`, `high`, `max` |
| `deepseekv4.1-flash-1017` | 1M | Text, image | `low`, `high` (default), `max`; off with `none` |
| `deepseekv4.1-flash-1017-interactive` | 1M | Text, image | Same levels as the standard variant |

`deepseekv4-pro` and `kimi-k3.1-pro` are Provisioned Throughput models and need
access enabled for your organisation. `sarvam-105b-conversations` is listed on
`/v2/models` and is also served on the legacy `/v1` endpoint. Sarvam Prism is a
decision model on `/v2/systemone`, not a chat model, so it is not exposed
through this class.

## Reasoning

Sarvam returns the thinking trace in `reasoning_content` and controls it with
`reasoning_effort`:

```python
Sarvam(id="sarvam-105b", reasoning_effort="high")
```

Accepted values depend on the model. `sarvam-105b` defaults to `low` and accepts
`none` to turn reasoning off. `glm5.3` and `glm5.3-flash` are always on and
accept `low`, `high`, and `max`.

## Structured output

`output_schema` uses Sarvam's native `json_schema` support. Verified behavior:

- `sarvam-105b`: use `reasoning_effort="none"`. With the default reasoning, a
  schema request can spend the whole token budget on reasoning and return
  `content: null`.
- `deepseekv4.1-flash-1017` and `deepseekv4.1-flash-1017-interactive`: work with
  `strict_output=True`.
- `glm5.3` and `glm5.3-flash`: `strict_output=True` returned schema-valid but
  semantically weak values in our tests; `strict_output=False` produced better
  results.
- `gemma4`: timed out on a `json_schema` request in our test, so it is not
  listed as a structured-output model.

```python
agent = Agent(
    model=Sarvam(id="sarvam-105b", reasoning_effort="none"),
    output_schema=MovieScript,
)
```

## Tools and images

Every chat model supports tool calling. The `tool_use.py` example uses a local
function so it stays fast and deterministic; web search adds external latency.
`glm5.3-flash`, `gemma4`, and `deepseekv4.1-flash-1017` also accept image input;
`gemma4` requires base64 data URIs and rejects remote `http(s)` URLs.

## Get an API key

Sign in at [dashboard.sarvam.ai](https://dashboard.sarvam.ai), create a Token
Factory API key, and export it:

```shell
export SARVAM_API_KEY=***
```

## Examples

```shell
# Basic agent (sync, async, streaming)
.venvs/demo/bin/python cookbook/90_models/sarvam/basic.py

# Create an agent from the "sarvam:<model-id>" string shorthand
.venvs/demo/bin/python cookbook/90_models/sarvam/string_model.py

# Structured output: return a typed Pydantic object
.venvs/demo/bin/python cookbook/90_models/sarvam/structured_output.py

# Reasoning agent: solve a logic puzzle with reasoning_effort="high"
.venvs/demo/bin/python cookbook/90_models/sarvam/reasoning_agent.py

# Tool use: local function calling
.venvs/demo/bin/python cookbook/90_models/sarvam/tool_use.py
```
