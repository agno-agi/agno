# MiniMax

[MiniMax](https://www.minimax.io/) exposes its text models through an
[OpenAI-compatible API](https://platform.minimax.io/docs/api-reference/text-openai-api),
so you can drive them through Agno the same way you'd drive any OpenAI-compatible
provider. The Agno `MiniMax` class defaults to `MiniMax-M3` and points at the
international endpoint `https://api.minimax.io/v1`.

### 1. Create and activate a virtual environment

See the repository [Development setup](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#development-setup).

### 2. Export your API key

```shell
export MINIMAX_API_KEY=***
```

Create an API key from the [MiniMax platform dashboard](https://platform.minimax.io/).

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run the basic example

```shell
python cookbook/90_models/minimax/basic.py
```

### Available models

The OpenAI-compatible endpoint exposes the current MiniMax family — see the
[models intro](https://platform.minimax.io/docs/guides/models-intro) for the
current catalog. As of writing:

| Model id | Notes |
| --- | --- |
| `MiniMax-M3` | Latest flagship, 1M context, 128K max output, image input; $0.60/M input tokens, $2.40/M output tokens, $0.12/M cache-read tokens (default) |
| `MiniMax-M2.7` | Previous flagship MoE (230B total / 10B active), 205k context |
| `MiniMax-M2.7-highspeed` | Same weights as M2.7, ~1.6–1.7× throughput |

Pass any of these as `MiniMax(id="...")`:

```python
from agno.agent import Agent
from agno.models.minimax import MiniMax

agent = Agent(model=MiniMax(id="MiniMax-M2.7-highspeed"))
```

### Tool use

```shell
python cookbook/90_models/minimax/tool_use.py
```

### Structured output

MiniMax does not implement OpenAI-style native `response_format` / strict
`json_schema`, so the Agno class sets `supports_native_structured_outputs =
False`. Use `use_json_mode=True` on the agent for Pydantic-shaped output:

```python
agent = Agent(
    model=MiniMax(id="MiniMax-M3"),
    output_schema=MovieScript,
    use_json_mode=True,
)
```

A full example lives in `structured_output.py`.

### Custom base URL

If you need to hit a different host (private deployment, regional endpoint,
etc.), pass `base_url`:

```python
MiniMax(id="MiniMax-M3", base_url="https://your-host.example.com/v1")
```
