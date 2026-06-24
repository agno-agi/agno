# Neosantara Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Export your `NEOSANTARA_API_KEY`

```shell
export NEOSANTARA_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U ddgs agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/90_models/neosantara/basic_stream.py
```

- Streaming off

```shell
python cookbook/90_models/neosantara/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search
```shell
python cookbook/90_models/neosantara/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/neosantara/structured_output.py
```

### 7. Run Async Examples

```shell
python cookbook/90_models/neosantara/async_basic.py
python cookbook/90_models/neosantara/async_basic_stream.py
python cookbook/90_models/neosantara/async_tool_use.py
```
