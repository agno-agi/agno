# Kenari Cookbook

> Note: Fork and clone this repository if needed.

Kenari is an AI model gateway with an OpenAI-compatible `/v1` API, live model discovery at `https://kenari.id/v1/models`, and additional native endpoint families such as Responses and Anthropic Messages.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `KENARI_API_KEY`

```shell
export KENARI_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run the basic Agent

```shell
python cookbook/90_models/kenari/basic.py
```

You can also use the string syntax:

```python
from agno.agent import Agent

agent = Agent(model="kenari:claude-sonnet-5")
```
