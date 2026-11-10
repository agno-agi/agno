# DashScope Cookbook

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `DASHSCOPE_API_KEY` or `QWEN_API_KEY`

Get your API key from: https://modelstudio.console.alibabacloud.com/?tab=model#/api-key

```shell
export DASHSCOPE_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/dashscope/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/90_models/dashscope/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/dashscope/structured_output.py
```

### 7. Run Agent that analyzes images

- Basic image analysis

```shell
python cookbook/90_models/dashscope/image_agent.py
```

- Image analysis with bytes

```shell
python cookbook/90_models/dashscope/image_agent_bytes.py
```

For more information about Qwen models and capabilities, visit:
- [Model Studio Console](https://modelstudio.console.alibabacloud.com/)
