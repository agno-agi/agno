# ModelScope Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export `MODELSCOPE_API_KEY`

You can visit https://www.modelscope.cn/my/myaccesstoken to obtain your MODELSCOPE_API_KEY for free.

All LLMs that support api inference on ModelScope can be used in agno

```shell
export MODELSCOPE_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/modelscope/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/modelscope/basic.py
```

### 5. Run agent with tools

- DuckDuckGo Search

```shell
python cookbook/models/modelscope/tool_use.py
```

### 6. Run Agent with rag

```shell
python cookbook/models/modelscope/rag_use.py
```