# ZAI Cookbook

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `ZAI_API_KEY`

Get your API key from: https://z.ai/manage-apikey/apikey-list

```shell
export ZAI_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai ddgs agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/zai/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/zai/basic.py
```

### 5. Run async Agent

- Async basic

```shell
python cookbook/models/zai/async_basic.py
```

- Async streaming

```shell
python cookbook/models/zai/async_basic_stream.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/zai/tool_use.py
```

- Async tool use

```shell
python cookbook/models/zai/async_tool_use.py
```

### 7. Run Agent that returns structured output

```shell
python cookbook/models/zai/structured_output.py
```

### 8. Run Agent that analyzes images

- Basic image analysis

```shell
python cookbook/models/zai/image_agent.py
```

- Image analysis with bytes

```shell
python cookbook/models/zai/image_agent_bytes.py
```

- Async image analysis

```shell
python cookbook/models/zai/async_image_agent.py
```

For more information about GLM models and capabilities, visit:

- [Model Overview](https://docs.z.ai/guides/overview/overview#featured-models)
