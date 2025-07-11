# Qwen Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `QWEN_API_KEY` or `DASHSCOPE_API_KEY`

```shell
export QWEN_API_KEY=***
# OR
export DASHSCOPE_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai duckduckgo-search duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/qwen/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/qwen/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/qwen/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/qwen/structured_output.py
```

## Notes

- Qwen models are provided by Alibaba Cloud's DashScope service
- The API is compatible with OpenAI's interface
- Supports both Chinese and English interactions
- Excellent performance for multilingual tasks 