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
pip install -U openai ddgs agno
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

For more information about Qwen models and capabilities, visit:
- [Model Studio Console](https://modelstudio.console.alibabacloud.com/)
