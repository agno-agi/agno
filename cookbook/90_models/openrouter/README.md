# OpenRouter Cookbook

> Note: Fork and clone this repository if needed

## Setup

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `OPENROUTER_API_KEY`

```shell
export OPENROUTER_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai agno
```

---

## Chat API Examples

The `chat/` folder contains examples using the OpenRouter Chat API.

### Basic Usage

```shell
# Streaming
python cookbook/90_models/openrouter/chat/basic_stream.py

# Non-streaming
python cookbook/90_models/openrouter/chat/basic.py

# Async
python cookbook/90_models/openrouter/chat/async_basic.py
```

### Tools and Structured Output

```shell
# Tool use
python cookbook/90_models/openrouter/chat/tool_use.py

# Async tool use
python cookbook/90_models/openrouter/chat/async_tool_use.py

# Structured output
python cookbook/90_models/openrouter/chat/structured_output.py
```

### Dynamic Model Router

```shell
python cookbook/90_models/openrouter/chat/dynamic_model_router.py
```

---

## Responses API Examples

The `responses/` folder contains examples using the OpenRouter Responses API (beta).

### Basic Usage

```shell
# Basic
python cookbook/90_models/openrouter/responses/basic.py

# Streaming
python cookbook/90_models/openrouter/responses/stream.py

# Async
python cookbook/90_models/openrouter/responses/async_basic.py
```

### Tools and Structured Output

```shell
# Tool use
python cookbook/90_models/openrouter/responses/tool_use.py

# Structured output
python cookbook/90_models/openrouter/responses/structured_output.py
```

### Model Fallback

OpenRouter supports automatic fallback to alternative models if the primary model fails:

```shell
python cookbook/90_models/openrouter/responses/fallback.py
```
