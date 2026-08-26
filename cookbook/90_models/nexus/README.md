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
uv pip install -U openai agno
```

### 5. Run basic Agent

```shell
python cookbook/90_models/nexus/basic.py
```

### 6. Run Agent with Tools

```shell
python cookbook/90_models/nexus/tool_use.py
```
