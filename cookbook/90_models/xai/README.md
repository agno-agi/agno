# xAI Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `XAI_API_KEY`

```shell
export XAI_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/92_models/xai/basic_stream.py
```

- Streaming off

```shell
python cookbook/92_models/xai/basic.py
```

### 5. Run with Tools

- DuckDuckGo Search

```shell
python cookbook/92_models/xai/tool_use.py
```

### 6. Run Agent with Image URL Input

```shell
python cookbook/92_models/xai/image_agent.py
```

### 7. Run Agent with Image Input

```shell
python cookbook/92_models/xai/image_agent_bytes.py
```

### 8. Run Agent with Image Input and Memory

```shell
python cookbook/92_models/xai/image_agent_with_memory.py
```

### 9. Run Agent with SuperGrok sign-in (no API key)

Sign in with a SuperGrok subscription through the OAuth device flow instead of
setting `XAI_API_KEY`. The stored token is encrypted with a dedicated key:

```shell
export XAI_TOKEN_ENCRYPTION_KEY=***
```

Generate a key with `python -c "from agno.utils.encryption import generate_encryption_key; print(generate_encryption_key())"`

```shell
python cookbook/90_models/xai/oauth_device_login.py
```
