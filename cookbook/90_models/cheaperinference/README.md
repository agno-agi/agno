# Cheaper Inference Cookbook

> Note: Fork and clone this repository if needed.

[Cheaper Inference](https://cheaperinference.com) is an OpenAI-compatible LLM gateway. Each model costs 15–60% less than the list price of its lab. Model ids are bare (no vendor prefix), e.g. `gpt-5.4`, `gpt-5.4-mini`, `claude-sonnet-5`, `gemini-3.1-pro`, `deepseek-v4-pro`, `glm-5.3`, `kimi-k3`.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `CHEAPER_INFERENCE_API_KEY`

Get your API key from: https://cheaperinference.com/signup

```shell
export CHEAPER_INFERENCE_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/cheaperinference/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/cheaperinference/tool_use.py
```

You can also use the string syntax:

```python
from agno.agent import Agent

agent = Agent(model="cheaperinference:gpt-5.4-mini")
```

## Resources

- [Website](https://cheaperinference.com)
- [Documentation](https://cheaperinference.com/docs)
- [Model List](https://cheaperinference.com/#models)
- **Base URL**: `https://api.cheaperinference.com/v1`
