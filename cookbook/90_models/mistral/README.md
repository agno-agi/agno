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
uv pip install -U mistralai ddgs duckdb yfinance agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/mistral/basic.py
```

### 5. Run Agent with Tools

- Custom tool

```shell
python cookbook/90_models/mistral/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/mistral/structured_output.py
```

### 7. Run Agent that uses memory

```shell
python cookbook/90_models/mistral/memory.py
```
