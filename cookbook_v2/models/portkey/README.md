# Portkey Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your Portkey keys

Get your API key from [app.portkey.ai](https://app.portkey.ai) and create a virtual key at [Virtual Keys](https://app.portkey.ai/virtual-keys).

```shell
export PORTKEY_API_KEY=***
export PORTKEY_VIRTUAL_KEY=***
```

### 3. Install libraries

```shell
pip install -U agno portkey-ai
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/portkey/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/portkey/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/models/portkey/tool_use.py
```