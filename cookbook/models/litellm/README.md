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
pip install -U openai 'litellm' duckduckgo-search duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/litellm/basic_hf.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/litellm/tool_use.py
```