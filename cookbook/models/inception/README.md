# Inception Labs Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `INCEPTION_API_KEY`

```shell
export INCEPTION_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai ddgs agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/inception/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/inception/basic.py
```

### 5. Run with Tools

- DuckDuckGo Search

```shell
python cookbook/models/inception/tool_use.py
```

### 6. Run async Agent

- Async streaming on

```shell
python cookbook/models/inception/async_basic_stream.py
```

- Async streaming off

```shell
python cookbook/models/inception/async_basic.py
```
