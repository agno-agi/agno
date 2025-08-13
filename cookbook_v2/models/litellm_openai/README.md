# LiteLLMOpenAI Cookbook

> Note: Fork and clone this repository if needed
### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `LITELLM_API_KEY`
Whichever model you use- openai, huggingface, xai, the api key will be by the name of `LITELLM_API_KEY`

```shell
export LITELLM_API_KEY=***
```

### 3. Install libraries

```shell
pip install -U openai 'litellm[proxy]' duckduckgo-search duckdb yfinance agno
```

### 4. Start the proxy server

```shell
litellm --model gpt-4o --host 127.0.0.1 --port 4000
```
or, if you want to use some other model like from Anthropic
```shell    
litellm --model claude-3-sonnet-20240229 --host 127.0.0.1 --port 4000
```

### 5. Run basic Agent

- Streaming on

```shell
python cookbook/models/litellm_proxy/basic_stream.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/litellm_proxy/tool_use.py
```