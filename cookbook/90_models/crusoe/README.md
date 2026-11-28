# Crusoe Cookbook

This cookbook demonstrates how to use Crusoe with the Agno framework. Crusoe Managed Inference
serves open-weight models (GLM, DeepSeek, Qwen, Gemma, gpt-oss, Nemotron) behind an
OpenAI-compatible API.

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `CRUSOE_API_KEY`

Get your API key from the Crusoe Cloud console (**Intelligence Foundry** > **Inference** >
**Create API Key**): https://console.crusoecloud.com

```shell
export CRUSOE_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/crusoe/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/crusoe/tool_use.py
```

### 6. Run Agent with Structured Output

```shell
python cookbook/90_models/crusoe/structured_output.py
```

## Model Ids

The endpoint reports its current catalogue at `GET /v1/models`. A few examples:

- `openai/gpt-oss-120b` (default)
- `zai-org/GLM-5.3`, `zai-org/GLM-5.3-Flash`
- `deepseek-ai/DeepSeek-V4.1-Flash`
- `Qwen/Qwen3.8-27B`
- `google/gemma-4-31b-it`
- `nvidia/NVIDIA-Nemotron-3.5-Super-VL`

The catalogue changes, so read it from `/v1/models` or the Available models page rather than
hardcoding it.

## Resources & Support

### Official Links
- [Website](https://crusoe.ai)
- [Documentation](https://docs.crusoecloud.com/managed-inference/overview)
- [Available models](https://docs.crusoecloud.com/serverless-inference/available-models)
- [Pricing](https://crusoe.ai/cloud/pricing)
- [Get API Key](https://console.crusoecloud.com)

### API Reference
- **Base URL**: `https://api.inference.crusoecloud.com/v1`
- **Models Endpoint**: `https://api.inference.crusoecloud.com/v1/models`
