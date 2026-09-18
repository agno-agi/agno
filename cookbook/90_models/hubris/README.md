# Hubris Cookbook

> Note: Fork and clone this repository if needed

[Hubris](https://hubris.pw) is an OpenAI-compatible LLM gateway billed in Russian rubles: one API key
for 500+ models from OpenAI, Anthropic, Google, DeepSeek, Qwen and others. Model ids use the full
`vendor/model` form from the [catalog](https://hubris.pw/models).

### 1. Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Export your `HUBRIS_API_KEY`

Create a key at [hubris.pw/keys](https://hubris.pw/keys).

```shell
export HUBRIS_API_KEY=sk-gw-***
```

### 3. Install libraries

```shell
pip install -U openai ddgs agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/90_models/hubris/basic.py
```

### 5. Run Agent with Tools

- Web search

```shell
python cookbook/90_models/hubris/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/hubris/structured_output.py
```
