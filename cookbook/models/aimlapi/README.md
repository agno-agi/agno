# AI/ML API Cookbook

### AI/ML API provides 300+ AI models including Deepseek, Gemini, ChatGPT. The models run at enterprise-grade rate limits and uptimes.

#### You can check provider docs [_here_](https://docs.aimlapi.com/?utm_source=agno&utm_medium=github&utm_campaign=integration)
#### And models overview is [_here_](https://aimlapi.com/models/?utm_source=agno&utm_medium=github&utm_campaign=integration)

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `AIMLAPI_API_KEY`

```shell
export AIMLAPI_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/aimlapi/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/aimlapi/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/aimlapi/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/aimlapi/structured_output.py
```

