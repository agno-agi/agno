# Qianfan Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `QIANFAN_API_KEY`

```shell
export QIANFAN_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/qianfan/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/qianfan/basic.py
```

### 5. Run Agent with Tools


- DuckDuckGo search

```shell
python cookbook/models/qianfan/tool_use.py
```
