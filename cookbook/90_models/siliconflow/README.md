# Siliconflow Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `SILICONFLOW_API_KEY`

```shell
export SILICONFLOW_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai duckduckgo-search duckdb agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/siliconflow/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/90_models/siliconflow/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/siliconflow/structured_output.py
```
