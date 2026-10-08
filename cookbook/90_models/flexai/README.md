# FlexAI Cookbook

This cookbook demonstrates how to use FlexAI with the Agno framework. FlexAI serves open-weight
models (DeepSeek, Qwen, GLM, Gemma, gpt-oss, Llama, MiniMax, ...) behind an OpenAI-compatible
Inference API.

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `FLEXAI_API_KEY`

Get your API key from: https://platform.flex.ai

```shell
export FLEXAI_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/flexai/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/flexai/tool_use.py
```

## Model Ids

The endpoint reports its current catalogue, with served context lengths and pricing, at
`GET /v1/models`. A few examples:

- `DeepSeek-V4-Flash-0731` (default) — 1M context, supports tool calls
- `GLM-5.3-Flash`, `GLM-5.2`
- `Qwen3.8-27B`, `Qwen3.8-Flash-Next`, `Qwen3-Coder-30B-A3B-Instruct-FP8`
- `gemma-4-31b-it`, `gpt-oss-120b`, `MiniMax-M2.7`

Tool calling works on every text chat model except `PaddleOCR-VL`. Image input works on
`DeepSeek-V4.1-Flash`, `gemma-4-26B-A4B-it`, `gemma-4-31b-it`, `GLM-5.3-Flash`, `Muse-Glimmer-30B`,
`Qwen3.5-9B`, `Qwen3.6-27B-FP8`, `Qwen3.6-35B-A3B-FP8`, `Qwen3.8-27B`, `Qwen3.8-Flash-Next` and
`Step-3.7-Flash`.

The catalogue changes, so read it from `/v1/models` rather than hardcoding it.

> **Note**: The chat endpoint rejects `n` greater than 1 and the `verbosity` parameter. Reasoning
> models return their reasoning in `reasoning_content`.

## Resources & Support

### 🔗 Official Links
- [Website](https://flex.ai)
- [Documentation](https://docs.flex.ai/inference-api/quickstart)
- [OpenAI Compatibility](https://docs.flex.ai/inference-api/reference/openai-compatibility)
- [Model List](https://flex.ai/models)
- [Pricing](https://flex.ai/pricing)
- [Get API Key](https://platform.flex.ai)

### 📖 API Reference
- **Base URL**: `https://api.flex.ai/v1`
- **Models Endpoint**: `https://api.flex.ai/v1/models`
