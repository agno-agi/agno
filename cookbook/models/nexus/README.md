# Nexus Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Download and set Nexus up:

[Nexus documentation](https://nexusrouter.com/docs).

### 3. Export Required Environment Variables

```shell
export OPENAI_API_KEY=***
export ANTHROPIC_API_KEY=***
```

### 4. Install libraries

```shell
pip install -U openai agno
```

### 5. Run basic Agent

- Streaming on

```shell
python cookbook/models/nexus/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/nexus/basic.py
```

### 6. Run Agent with Tools

- Streaming on

```shell
python cookbook/models/nexus/tool_use.py
```

- Streaming off

```shell
python cookbook/models/nexus/tool_use.py
```
