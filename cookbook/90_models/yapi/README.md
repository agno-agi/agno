# Y-API Cookbook

This cookbook demonstrates how to use Y-API with the Agno framework. Y-API is an
OpenAI-compatible gateway that serves models from several vendors behind a single endpoint,
with org-prefixed model ids (`deepseek/deepseek-v4-flash`, `z-ai/glm-5.3`, `openai/gpt-5.6-sol`, ...).

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `YAPI_API_KEY`

Get your API key from: https://y-api.bestvirtualgoods.com/app/keys

```shell
export YAPI_API_KEY=sk-***
```

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/yapi/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/yapi/tool_use.py
```

## Model Ids

The endpoint reports its current catalogue at `GET /v1/models`, and the ids are org-prefixed
(`<org>/<model>`). A few examples:

- `deepseek/deepseek-v4-flash` (default) — the cheapest option, and it supports tool calls
- `deepseek/deepseek-v4-pro`
- `z-ai/glm-5.3`, `z-ai/glm-5.2`
- `moonshotai/kimi-k3`
- `openai/gpt-5.6-sol`, `openai/gpt-5.6-terra`, `openai/gpt-5.6-luna`, `openai/gpt-6-astra`
- `qwen/qwen3.8-flash`, `tencent/hy3`, `xiaomi/mimo-v2.5`

The catalogue changes, so read it from `/v1/models` rather than hardcoding it.

> **Note**: The four `openai/gpt-5.6-*` and `openai/gpt-6-astra` ids require an explicit
> `reasoning_effort` when `tools` are sent — without it the endpoint answers
> `Function tools with reasoning_effort are not supported`. If you hit that with an agent,
> pass `reasoning_effort="low"` on the model, or use one of the other ids above.

## Resources & Support

### 🔗 Official Links
- [Website](https://y-api.bestvirtualgoods.com)
- [Documentation](https://y-api.bestvirtualgoods.com/docs)
- [Model List](https://y-api.bestvirtualgoods.com/models)
- [Pricing](https://y-api.bestvirtualgoods.com/pricing)
- [Get API Key](https://y-api.bestvirtualgoods.com/app/keys)

### 📖 API Reference
- **Base URL**: `https://api.y-api.bestvirtualgoods.com/v1`
- **Models Endpoint**: `https://api.y-api.bestvirtualgoods.com/v1/models`
