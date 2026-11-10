# Groq Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `GROQ_API_KEY`

```shell
export GROQ_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U groq ddgs duckdb yfinance agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/groq/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/90_models/groq/tool_use.py
```

- Research using Exa

```shell
python cookbook/90_models/groq/research_agent_exa.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/groq/structured_output.py
```

### 7. Run Agent that uses storage

Please run pgvector in a docker container using:

```shell
./cookbook/scripts/run_pgvector.sh
```

Then run the following:

```shell
python cookbook/90_models/groq/db.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/90_models/groq/knowledge.py
```
Take note that by default, OpenAI embeddings are used and an API key will be required. Alternatively, there are other embedders available that can be used. See more examples in `/cookbook/07_knowledge/09_archive/embedders`

### 9. Run Agent that analyzes an image

```shell
python cookbook/90_models/groq/image_agent.py
```
