# OrcaRouter Cookbook

> Note: Fork and clone this repository if needed

[OrcaRouter](https://www.orcarouter.ai) is an OpenAI-compatible model router. Point the
`id` at any model in the [catalog](https://www.orcarouter.ai/models) (e.g.
`openai/gpt-4o-mini`, `anthropic/claude-opus-4.8`) or at the virtual router
`orcarouter/auto`, which selects an upstream per request based on your
[console routing policy](https://www.orcarouter.ai/console/routing).

## Setup

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `ORCAROUTER_API_KEY`

OrcaRouter API keys start with `sk-orca-`.

```shell
export ORCAROUTER_API_KEY=sk-orca-***
```

### 3. Install libraries

```shell
pip install -U openai agno
```

---

## Chat API Examples

The `chat/` folder contains examples using the OrcaRouter Chat API.

### Basic Usage

```shell
python cookbook/90_models/orcarouter/chat/basic.py
```

### Tools and Structured Output

```shell
# Tool use
python cookbook/90_models/orcarouter/chat/tool_use.py

# Structured output
python cookbook/90_models/orcarouter/chat/structured_output.py
```

### Dynamic Model Router

Provide a `models` list to fall back through alternatives if the primary model fails:

```shell
python cookbook/90_models/orcarouter/chat/dynamic_model_router.py
```
