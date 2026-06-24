# DeepInfra Cookbook

> Note: Fork and clone this repository if needed

> Note: DeepInfra does not appear to include models that support structured outputs.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `DEEPINFRA_API_KEY`

```shell
export DEEPINFRA_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/92_models/deepinfra/basic_stream.py
```

- Streaming off

```shell
python cookbook/92_models/deepinfra/basic.py
```

### 5. Run Async Agent

- Streaming on

```shell
python cookbook/92_models/deepinfra/async_basic_stream.py
```

- Streaming off

```shell
python cookbook/92_models/deepinfra/async_basic.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/92_models/deepinfra/tool_use.py
```

- Async DuckDuckGo Search

```shell
python cookbook/92_models/deepinfra/async_tool_use.py
```

### 6. Run Agent that returns JSON output defined by the response model

```shell
python cookbook/92_models/deepinfra/json_output.py
```
