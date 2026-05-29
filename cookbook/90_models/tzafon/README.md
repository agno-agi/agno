# Tzafon Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Get and export your `TZAFON_API_KEY`

Sign up at [lightcone.ai](https://lightcone.ai) and copy your API key from the developer dashboard at [lightcone.ai/developer](https://lightcone.ai/developer). Tzafon's API is served through Lightcone, so `tzafon.ai` redirects there.

```shell
export TZAFON_API_KEY=sk_***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

Runs sync, sync + streaming, async, and async + streaming responses.

```shell
python cookbook/90_models/tzafon/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/90_models/tzafon/tool_use.py
```

### 6. Run Agent with Structured Output

Demonstrates both JSON mode and native structured output.

```shell
python cookbook/90_models/tzafon/structured_output.py
```
