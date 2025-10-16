# NetMind Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `NETMIND_API_KEY`

```shell
export NETMIND_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U netmind openai duckduckgo-search duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/netmind/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/netmind/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search
```shell
python cookbook/models/netmind/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/netmind/structured_output.py
```

### 7. Run Agent with Image URL Input

```shell
python cookbook/models/netmind/image_agent.py
```

### 8. Run Agent with Image Input

```shell
python cookbook/models/netmind/image_agent_bytes.py
```

### 9. Run Agent with Image Input and Memory

```shell
python cookbook/models/netmind/image_agent_with_memory.py
```
