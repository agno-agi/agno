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

### 10. Run Agent with SuperGrok sign-in from chat

Sign in from inside the conversation instead of the terminal: a sign-in agent
hands the user an approval link on one turn and finishes the sign-in on the
next, and a Grok agent then answers on the subscription. Two agents, because an
agent cannot sign in to the model it is already running on - so the sign-in
agent runs on a model that does not need the SuperGrok session. Use this for
chatbots and web UIs.

```shell
export OPENAI_API_KEY=***
export XAI_TOKEN_ENCRYPTION_KEY=***
```

```shell
python cookbook/90_models/xai/oauth_chat_signin.py
```

### 11. Run Agents with per-user SuperGrok sign-in

Several people share one deployment and each spends their own subscription. The
token is stored under the user_id the run carries, and the model resolves that
user's token per request. A user who has not signed in falls back to the
deployment's own session; `require_user_token=True` on the model refuses that
fallback and requires everyone to sign in first. Per-user tokens need a
database - one token file cannot hold a session each. Same two keys as above:

```shell
python cookbook/90_models/xai/oauth_multi_user.py
```
