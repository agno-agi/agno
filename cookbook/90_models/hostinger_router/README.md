# Hostinger Router Cookbook

This cookbook demonstrates how to use Hostinger Router with the Agno framework. Hostinger
Router is an OpenAI-compatible gateway to models from OpenAI, Anthropic, Google and others
(`https://router.hostinger.com/v1`).

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `HOSTINGER_ROUTER_API_KEY`

Create an API key in the Hostinger Router dashboard and export it:

```shell
export HOSTINGER_ROUTER_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/hostinger_router/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/hostinger_router/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/hostinger_router/structured_output.py
```

## Model Ids

The examples use `gpt-5-mini`. Hostinger Router model ids carry no vendor prefix, so the same
provider serves `gpt-5-mini`, `claude-sonnet-5`, `gemini-3.5-flash` and others, and some models
also have `-eu` / `-us` regional variants:

```python
from agno.models.hostinger_router import HostingerRouter

HostingerRouter(id="gpt-5-mini")
HostingerRouter(id="claude-sonnet-5-eu")
```

The catalog is public: `GET /v1/models` lists every model the gateway currently serves.

You can also select the provider by string, which resolves to the same class:

```python
from agno.agent import Agent

agent = Agent(model="hostinger-router:gpt-5-mini")
```

## Resources & Support

### Official Links
- [Website](https://hostinger.com)
- [Router documentation](https://router.hostinger.com)

### API Reference
- **Base URL**: `https://router.hostinger.com/v1`
- **Models Endpoint**: `https://router.hostinger.com/v1/models`
- **Authentication**: Bearer token from the `HOSTINGER_ROUTER_API_KEY` environment variable
