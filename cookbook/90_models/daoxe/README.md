# DaoXE Cookbook

> Multi-model multi-protocol API gateway (OpenAI-compatible Chat Completions)

### 1. Export keys

```shell
export DAOXE_API_KEY=***
export DAOXE_MODEL=***   # exact ID from your account GET /v1/models
```

### 2. Install

```shell
uv pip install -U openai agno
```

### 3. Run

```shell
python cookbook/90_models/daoxe/basic.py
python cookbook/90_models/daoxe/tool_use.py
python cookbook/90_models/daoxe/structured_output.py
```

DaoXE also exposes OpenAI Responses and Anthropic Messages for other clients; these examples use Chat Completions via `agno.models.daoxe.DaoXE` (`OpenAILike`).

Not available in mainland China.

Docs / examples: https://github.com/seven7763/DaoXE-AI
