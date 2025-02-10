# Ollama Hermes Cookbook

> Note: Fork and clone this repository if needed

### 1. [Install](https://github.com/ollama/ollama?tab=readme-ov-file#macos) ollama and run models

Run your chat model

```shell
ollama pull hermes3
```

### 2. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 3. Install libraries

```shell
pip install -U ollama duckduckgo-search duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/hermes/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/hermes/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo search

```shell
python cookbook/models/hermes/tool_use.py
```


### 6. Run Agent that returns structured output

```shell
python cookbook/models/hermes/structured_output.py
```
