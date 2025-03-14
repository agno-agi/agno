# OpenAI Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `OPENAI_API_KEY`

```shell
export OPENAI_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai 'litellm[proxy]' duckduckgo-search duckdb yfinance agno
```

### 4. Start the proxy server

```shell
litellm --model gpt-4o
```


### 5. Run basic Agent

- Streaming on

```shell
python cookbook/models/openai/basic_stream.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/openai/tool_use.py
```
