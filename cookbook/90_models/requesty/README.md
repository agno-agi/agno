# Requesty Cookbook

> Note: Fork and clone this repository if needed

Requesty AI is an LLM gateway with AI governance. See their [website](https://www.requesty.ai) for more information.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `REQUESTY_API_KEY`

```shell
export REQUESTY_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs duckdb yfinance agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/requesty/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/90_models/requesty/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/requesty/structured_output.py
```
