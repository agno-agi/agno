# Lightning Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `LIGHTNING_API_KEY`

```shell
export LIGHTNING=***
```

### 3. Install libraries

```shell
pip install -U openai agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/lightning/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/lightning/basic.py
```

### 5. Run Agent with Tools

- Streaming on

```shell
python cookbook/models/lightning/tool_use_stream.py
```

- Streaming off

```shell
python cookbook/models/lightning/tool_use.py
```
