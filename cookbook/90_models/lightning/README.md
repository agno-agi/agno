# Lightning AI Cookbook

> Note: Fork and clone this repository if needed.

Lightning AI Model APIs expose hosted models behind an OpenAI-compatible `/v1` API. Get an API key from your Lightning AI account under Global Settings -> Keys.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `LIGHTNING_API_KEY`

```shell
export LIGHTNING_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run the basic Agent

```shell
python cookbook/90_models/lightning/basic.py
```

### 5. Run the Agent with tools

```shell
python cookbook/90_models/lightning/tool_use.py
```

You can also use the string syntax:

```python
from agno.agent import Agent

agent = Agent(model="lightning:openai/gpt-5-nano")
```
