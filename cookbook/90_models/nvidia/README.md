# Nvidia Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `NVIDIA_API_KEY`

```shell
export NVIDIA_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/nvidia/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/nvidia/tool_use.py
```
