# LMStudio Cookbook

> Note: Fork and clone this repository if needed

### 1. [Install](https://lmstudio.ai/) LMStudio and download a model

Run your chat model using LMStudio. For the examples below make sure to get `qwen2.5-7b-instruct-1m`. Please also make sure that the status is set to `Running` and the model is reachable at `http://127.0.0.1:1234/v1`.

### 2. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 3. Install libraries

```shell
pip install -U ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/lmstudio/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/lmstudio/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/lmstudio/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/lmstudio/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/lmstudio/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/models/lmstudio/knowledge.py
```

### 9. Run Agent that uses memory

```shell
python cookbook/models/lmstudio/memory.py
```

### 10. Run Agent that takes image as input

```shell
python cookbook/models/lmstudio/image_agent.py
```
