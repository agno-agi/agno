# LangDB Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `LANGDB_API_KEY` and `LANGDB_PROJECT_ID`

```shell
export LANGDB_API_KEY=***
export LANGDB_PROJECT_ID=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs duckdb yfinance agno
```

### 4. Run Agent without Tools

```shell
python cookbook/90_models/langdb/basic.py
```

### 5. Run Agent with Tools

- Yahoo Finance without streaming

```shell
python cookbook/90_models/langdb/agent.py
```

- Web Search Agent

```shell
python cookbook/90_models/langdb/web_search.py
```

- Data Analyst

```shell
python cookbook/90_models/langdb/data_analyst.py
```

- Finance Agent

```shell
python cookbook/90_models/langdb/finance_agent.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/langdb/structured_output.py
```

