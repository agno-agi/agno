# Perplexity Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `PERPLEXITY_API_KEY`

```shell
export PERPLEXITY_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U ddgs duckdb agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/perplexity/basic.py
```

### 5. Run Agent with Tools

- Web Search

```shell
python cookbook/90_models/perplexity/web_search.py
```

### 6. Run Agent with Knowledge

```shell
python cookbook/90_models/perplexity/knowledge.py
```

