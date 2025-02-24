# xAI Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `XAI_API_KEY`

```shell
export XAI_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai duckduckgo-search duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/xai/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/xai/basic.py
```

### 5. Run with Tools

- DuckDuckGo Search

```shell
python cookbook/models/xai/tool_use.py
```

### 6. Run Agent with Image URL Input

```shell
python cookbook/models/xai/image_agent.py
```

### 7. Run Agent with Image Input

```shell
python cookbook/models/xai/image_agent_bytes.py
```

### 8. Run Agent with Image Input and Memory

```shell
python cookbook/models/xai/image_agent_with_memory.py
``