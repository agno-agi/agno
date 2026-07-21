# TokenLab Cookbook

> Note: Fork and clone this repository if needed.

TokenLab is an AI model gateway with an OpenAI-compatible `/v1` API, live model discovery at `https://api.tokenlab.sh/v1/models`, and additional native endpoint families such as Responses, Anthropic Messages, and Gemini-compatible APIs.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `TOKENLAB_API_KEY`

```shell
export TOKENLAB_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run the basic Agent

```shell
python cookbook/90_models/tokenlab/basic.py
```

You can also use the string syntax:

```python
from agno.agent import Agent

agent = Agent(model="tokenlab:gpt-5.4-mini")
```
