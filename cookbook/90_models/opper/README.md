# Opper Cookbook

> Note: Fork and clone this repository if needed

[Opper](https://opper.ai) is an EU-hosted LLM gateway. One API key reaches models from OpenAI, Anthropic, Google, Mistral, DeepSeek, Moonshot and open-weight vendors through an OpenAI-compatible endpoint at `https://api.opper.ai/v3/compat`.

Model ids are bare pool names such as `claude-sonnet-4-6` or `gpt-5.5`, where a pool is every provider serving that model and Opper picks the route per request. A `provider/model` id such as `azure/gpt-5.5` pins one provider or region instead. Browse the catalog at [opper.ai/models](https://opper.ai/models).

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `OPPER_API_KEY`

Create a key in the [Opper console](https://platform.opper.ai).

```shell
export OPPER_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/opper/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/90_models/opper/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/opper/structured_output.py
```
