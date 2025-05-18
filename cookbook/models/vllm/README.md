# Vllm Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `VLLM_BASE_URL`

```shell
export VLLM_BASE_URL="http://localhost:8000"
```

### 3. Install libraries

```shell
pip install -U openai duckduckgo-search duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/vllm/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/vllm/basic.py
```

### 5. Run with Tools

- DuckDuckGo Search

```shell
python cookbook/models/vllm/tool_use.py
```
