# Inception Labs

[Inception](https://www.inceptionlabs.ai/) builds Mercury, a family of
diffusion large language models (dLLMs) that refine all tokens in parallel
instead of generating them left-to-right, making them very fast. Inception
exposes the models through an
[OpenAI-compatible API](https://docs.inceptionlabs.ai/), so you can drive
them through Agno the same way you'd drive any OpenAI-compatible provider.
The Agno `Inception` class defaults to `mercury-2` and points at
`https://api.inceptionlabs.ai/v1`.

### 1. Create and activate a virtual environment

See the repository [Development setup](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#development-setup).

### 2. Get an API key

1. Create an account at the [Inception Platform](https://platform.inceptionlabs.ai/).
2. Open the dashboard and go to **API Keys** (`https://platform.inceptionlabs.ai/dashboard/api-keys`).
3. Create a key and export it:

```shell
export INCEPTION_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run the basic example

```shell
python cookbook/90_models/inception/basic.py
```

### Available models

| Model id | Notes |
| --- | --- |
| `mercury-2` | Flagship reasoning dLLM. Tunable reasoning depth, 128K context, native tool use, JSON output. Default in the Agno class. |
| `mercury-coder-small` | Coding-focused variant for latency-sensitive code workflows. |

> The original `mercury` model is only available to accounts created before
> February 24, 2026. New accounts should use `mercury-2` (or the Edit/coder
> variants) instead.

Pass any of these as `Inception(id="...")`:

```python
from agno.agent import Agent
from agno.models.inception import Inception

agent = Agent(model=Inception(id="mercury-2"))
```

### Examples

| Example | What it shows |
| --- | --- |
| `basic.py` | Sync, sync+streaming, async, and async+streaming runs. |
| `tool_use.py` | Agent calling a tool (web search), with streaming. |
| `structured_output.py` | Pydantic-typed output via JSON mode. |

### Structured output

Inception's OpenAI-compatible endpoint does not implement native
`json_schema` structured outputs, so the Agno class sets
`supports_native_structured_outputs = False`. Use `use_json_mode=True` on the
agent for Pydantic-shaped output:

```python
agent = Agent(
    model=Inception(id="mercury-2"),
    output_schema=MovieScript,
    use_json_mode=True,
)
```

A full example lives in `structured_output.py`.

### Custom base URL

If you need a different host (private deployment, regional endpoint, etc.),
pass `base_url`:

```python
Inception(id="mercury-2", base_url="https://your-host.example.com/v1")
```
