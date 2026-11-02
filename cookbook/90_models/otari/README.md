# Otari Cookbook

This cookbook demonstrates how to use Otari with the Agno framework. [Otari](https://github.com/mozilla-ai/otari)
is an open-source, OpenAI-compatible LLM gateway by Mozilla.ai that adds API keys, budgets, usage
tracking and routing in front of your model providers. Use the hosted gateway at
`https://api.otari.ai/api/v1` or run your own.

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `OTARI_API_KEY`

```shell
export OTARI_API_KEY=***
```

For a self-hosted gateway, also point `OTARI_BASE_URL` at it:

```shell
export OTARI_BASE_URL=http://localhost:8000/api/v1
```

Accounts in otari.ai's EU region use `https://eu.api.otari.ai/api/v1` instead, so set
`OTARI_BASE_URL` to that host.

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/otari/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/otari/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/otari/structured_output.py
```

## Model Ids

The model id is sent to the gateway unchanged, so any selector your gateway accepts works:

- `openai:gpt-4o` or `anthropic:claude-sonnet-4-6` (`provider:model`) pins the provider.
- `openai/gpt-4o` on otari.ai lets Otari choose where to serve the model.
- An alias or routing policy name configured on the gateway, such as `support-agent`.

With the string syntax, everything after the first `otari:` is the model id, for example
`model="otari:anthropic:claude-sonnet-4-6"`.

## Resources & Support

### Official Links
- [GitHub](https://github.com/mozilla-ai/otari)
- [Website](https://otari.ai)

### API Reference
- **Base URL**: `https://api.otari.ai/api/v1`
- **Chat Completions Endpoint**: `https://api.otari.ai/api/v1/chat/completions`
