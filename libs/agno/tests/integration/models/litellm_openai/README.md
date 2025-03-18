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


### 5. Run tests

```shell
pytest libs/agno/tests/integration/models/litellm_openai/test_basic.py -v
pytest libs/agno/tests/integration/models/litellm_openai/test_tool_use.py -v
```