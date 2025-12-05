# Fireworks AI Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `FIREWORKS_API_KEY`

```shell
export FIREWORKS_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/fireworks/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/fireworks/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/fireworks/tool_use.py
```


### 6. Run Agent that returns structured output

```shell
python cookbook/models/fireworks/structured_output.py
```


