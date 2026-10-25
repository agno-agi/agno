# Heabsy Cookbook

This cookbook demonstrates how to use Heabsy with the Agno framework. Heabsy is an
OpenAI-compatible inference API for open models (`https://api.heabsy.com/v1`).

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `HEABSY_API_KEY`

Get an API key in the Heabsy console (https://platform.heabsy.com); accounts are opened on
request at https://heabsy.com/contacts.

```shell
export HEABSY_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/heabsy/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/heabsy/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/heabsy/structured_output.py
```

## Model Ids

The examples use `qwen38` (Qwen3.8 27B): 262,144-token context, up to 32,768 output tokens,
vision input, tool calling and structured output. The endpoint lists the current models at
`GET /v1/models`, and the catalog is at https://heabsy.com/models.

Reasoning is on or off per request through `chat_template_kwargs.enable_thinking`, for example:

```python
Heabsy(id="qwen38", extra_body={"chat_template_kwargs": {"enable_thinking": False}})
```

Models in the EEA tier run on dedicated GPUs in EEA data centres with zero data retention;
models routed through third parties are labelled as such in the catalog.

Heabsy has no `/v1/embeddings` endpoint, so use a different embedder for knowledge bases.

## Resources & Support

### Official Links
- [Website](https://heabsy.com)
- [Platform](https://heabsy.com/platform)
- [Model Catalog](https://heabsy.com/models)
- [API Reference](https://api.heabsy.com/docs)
- [Console](https://platform.heabsy.com)

### API Reference
- **Base URL**: `https://api.heabsy.com/v1`
- **Models Endpoint**: `https://api.heabsy.com/v1/models`
