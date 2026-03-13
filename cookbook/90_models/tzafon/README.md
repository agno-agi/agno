# Tzafon Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `TZAFON_API_KEY`

```shell
export TZAFON_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/90_models/tzafon/basic_stream.py
```

- Streaming off

```shell
python cookbook/90_models/tzafon/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/90_models/tzafon/tool_use.py
```
