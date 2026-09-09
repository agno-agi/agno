# DaoXE Cookbook

DaoXE is an OpenAI-compatible gateway. These examples use the Chat Completions
path via `agno.models.daoxe.DaoXE` (`OpenAILike`).

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `DAOXE_API_KEY`

```shell
export DAOXE_API_KEY=***
```

Model IDs are scoped to your account catalog. List them with `GET /v1/models`
and export one to override the default:

```shell
export DAOXE_MODEL=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/daoxe/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/daoxe/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/daoxe/structured_output.py
```

### 7. Run Agent with retries

```shell
python cookbook/90_models/daoxe/retry.py
```
