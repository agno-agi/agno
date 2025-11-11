# CometAPI Cookbook

This cookbook demonstrates how to use CometAPI with the Agno framework. CometAPI provides unified access to multiple LLM providers (GPT, Claude, Gemini, DeepSeek, Qwen, and more) through a single OpenAI-compatible interface.

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `COMETAPI_KEY`

Get your API key from: https://api.cometapi.com/console/token

```shell
export COMETAPI_KEY=sk-***
```

### 3. Install libraries

```shell
pip install -U openai duckduckgo-search duckdb agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/cometapi/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/cometapi/basic.py
```

### 5. Run Async examples

- Basic async

```shell
python cookbook/models/cometapi/async_basic.py
```

- Async with streaming

```shell
python cookbook/models/cometapi/async_basic_stream.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/cometapi/tool_use.py
```

- Tool use with streaming

```shell
python cookbook/models/cometapi/tool_use_stream.py
```

- Async tool use

```shell
python cookbook/models/cometapi/async_tool_use.py
```

- Async tool use with streaming

```shell
python cookbook/models/cometapi/async_tool_use_stream.py
```

### 7. Run Agent that returns structured output

```shell
python cookbook/models/cometapi/structured_output.py
```

### 8. Image analysis examples

- Basic image analysis

```shell
python cookbook/models/cometapi/image_agent.py
```

- Image analysis with memory

```shell
python cookbook/models/cometapi/image_agent_with_memory.py
```

### 9. Multi-model showcase

```shell
python cookbook/models/cometapi/multi_model.py
```

## Available Models

CometAPI provides access to multiple LLM providers through a unified interface. For the most up-to-date list of supported models and pricing information, please visit:

📋 **Official Model List & Pricing**: https://api.cometapi.com/pricing

### Popular Models (Examples)

#### GPT Series
- `gpt-5-mini` (default)
- `gpt-5-chat-latest`
- `chatgpt-4o-latest`
- `gpt-5-nano`
- `gpt-4o-mini`
- `o4-mini-2025-04-16`
- `o3-pro-2025-06-10`

#### Claude Series
- `claude-opus-4-1-20250805`
- `claude-sonnet-4-20250514`
- `claude-3-7-sonnet-latest`
- `claude-3-5-haiku-latest`

#### Gemini Series
- `gemini-2.5-pro`
- `gemini-2.5-flash`
- `gemini-2.0-flash`

#### Grok Series
- `grok-4-0709`
- `grok-3`
- `grok-3-mini`

#### DeepSeek Series
- `deepseek-v3.1`
- `deepseek-v3`
- `deepseek-r1-0528`
- `deepseek-chat`
- `deepseek-reasoner`

#### Qwen Series
- `qwen3-30b-a3b`
- `qwen3-coder-plus-2025-07-22`

> **Note**: Model availability and names may change. Always refer to the [official pricing page](https://api.cometapi.com/pricing) for the most current information.

## Error Handling

If you encounter authentication errors, make sure your API key is correctly set:

```python
from agno.models.cometapi import CometAPI

# Test API key
model = CometAPI()
available_models = model.get_available_models()
print(f"Found {len(available_models)} available models")
```

## Resources & Support

### 🔗 Official Links
- [Website](https://www.cometapi.com/?utm_source=agno&utm_campaign=integration&utm_medium=integration&utm_content=integration)
- [API Documentation](https://api.cometapi.com/doc)
- [Model List & Pricing](https://api.cometapi.com/pricing)
- [Get API Key](https://api.cometapi.com/console/token)

### 👥 Community & Development
- [GitHub](https://github.com/cometapi-dev)
- [Discord Community](https://discord.com/invite/HMpuV6FCrG)

### 📖 API Reference
- **Base URL**: `https://api.cometapi.com/v1/`
- **Models Endpoint**: `https://api.cometapi.com/v1/models`

### 💡 Tips
- Use the `/models` endpoint to get real-time model availability
- Model names and availability may change - always check the official pricing page
- Join the Discord community for support and updates
