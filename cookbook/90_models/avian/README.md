# Avian Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `AVIAN_API_KEY`

```shell
export AVIAN_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/avian/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/90_models/avian/tool_use.py
```

### 6. Run Agent that returns JSON output defined by the response model

```shell
python cookbook/90_models/avian/json_output.py
```

### 7. Run Agent with string model syntax

```shell
python cookbook/90_models/avian/string_model.py
```
