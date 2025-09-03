# Mistral Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `MISTRAL_API_KEY`

```shell
export MISTRAL_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U mistralai ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/mistral/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/mistral/basic.py
```

### 5. Run Agent with Tools


- DuckDuckGo search

```shell
python cookbook/models/mistral/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/mistral/structured_output.py
```

### 7. Run Agent that uses memory

```shell
python cookbook/models/mistral/memory.py
```
