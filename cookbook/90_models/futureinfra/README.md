# FutureInfra Cookbook

This cookbook demonstrates how to use FutureInfra with the Agno framework. FutureInfra is a
Korean cloud provider whose AI API is an OpenAI-compatible router that serves models from
several vendors behind a single endpoint, with `provider/model` ids
(`openai/gpt-4o-mini`, `anthropic/claude-sonnet-4`, `google/gemini-2.5-flash`, ...).

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `FUTUREINFRA_API_KEY`

Get your API key from: https://futureinfra.ai/console/?screen=ai-router

```shell
export FUTUREINFRA_API_KEY=pk_live_***
```

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/futureinfra/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/futureinfra/tool_use.py
```

## Model Ids

The endpoint reports its current catalogue at `GET /v1/ai/models`, and the ids are
`provider/model`. A few examples:

- `openai/gpt-4o-mini` (default)
- `openai/gpt-4o`
- `anthropic/claude-sonnet-4`
- `google/gemini-2.5-flash`
- `deepseek/deepseek-chat`

The catalogue changes, so read it from `/v1/ai/models` rather than hardcoding it.

## Resources & Support

### 🔗 Official Links
- [Website](https://futureinfra.ai/)
- [AI API](https://futureinfra.ai/ai/)
- [Documentation](https://futureinfra.ai/docs/)
- [Get API Key](https://futureinfra.ai/console/?screen=ai-router)

### 📖 API Reference
- **Base URL**: `https://futureinfra.ai/v1/ai`
- **Models Endpoint**: `https://futureinfra.ai/v1/ai/models`
