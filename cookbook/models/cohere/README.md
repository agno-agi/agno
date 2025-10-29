# Cohere Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `CO_API_KEY`

```shell
export CO_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U cohere ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/cohere/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/cohere/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/cohere/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/cohere/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/cohere/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/models/cohere/knowledge.py
```

### 9. Run Agent that uses memory

```shell
python cookbook/models/cohere/memory.py
```
