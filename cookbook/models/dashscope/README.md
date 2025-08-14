# DashScope Cookbook

Qwen models are provided by Alibaba Cloud through DashScope API with OpenAI-compatible interface.

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `DASHSCOPE_API_KEY`

Get your API key from: https://modelstudio.console.alibabacloud.com/?tab=model#/api-key

```shell
export DASHSCOPE_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai duckduckgo-search duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/dashscope/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/dashscope/basic.py
```

### 5. Run async Agent

- Async basic

```shell
python cookbook/models/dashscope/async_basic.py
```

- Async streaming

```shell
python cookbook/models/dashscope/async_basic_stream.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/dashscope/tool_use.py
```

- Async tool use

```shell
python cookbook/models/dashscope/async_tool_use.py
```

### 7. Run Agent that returns structured output

```shell
python cookbook/models/dashscope/structured_output.py
```

### 8. Run Agent that analyzes images

- Basic image analysis

```shell
python cookbook/models/dashscope/image_agent.py
```

- Image analysis with bytes

```shell
python cookbook/models/dashscope/image_agent_bytes.py
```

- Async image analysis

```shell
python cookbook/models/dashscope/async_image_agent.py
```

- Multi-image comparison

```shell
python cookbook/models/dashscope/multi_image_agent.py
```

## Available Models

### Text Models

The Qwen models support different capabilities:

- `qwen-plus` - Most capable Qwen model (default)
- `qwen-turbo` - Faster and more cost-effective
- `qwen-max` - Most advanced model with highest performance
- `qwen-long` - Optimized for long context understanding

### Vision Models

The Qwen-VL models support image analysis:

- `qwen-vl-plus` - Advanced vision-language model for image analysis
- `qwen-vl-max` - Most capable vision model with highest accuracy
- `qwen-vl-plus-latest` - Latest version of the vision model

## Regions

The integration supports two regions:

- **Singapore (International)**: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` (default)
- **China (Beijing)**: `https://dashscope.aliyuncs.com/compatible-mode/v1`

To use the China region, specify the base_url when creating the model:

```python
from agno.models.qwen import Qwen

model = Qwen(
    id="qwen-plus",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)
```

## Features

- ✅ Chat completions
- ✅ Streaming
- ✅ Async support
- ✅ Tool calling
- ✅ Structured outputs
- ✅ Native JSON schema support
- ✅ Image analysis (Qwen-VL models)
- ✅ Multi-image comparison
- ✅ Vision-language understanding

For more information about Qwen models and capabilities, visit:
- [Model Studio Console](https://modelstudio.console.alibabacloud.com/)
- [DashScope Documentation](https://www.alibabacloud.com/help/en/model-studio/developer-reference/error-code)
