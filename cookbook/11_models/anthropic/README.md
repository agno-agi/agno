# Anthropic Claude

[Models overview](https://docs.anthropic.com/claude/docs/models-overview)

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Set your `ANTHROPIC_API_KEY`

```shell
export ANTHROPIC_API_KEY=xxx
```

### 3. Install libraries

```shell
pip install -U anthropic ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/anthropic/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/anthropic/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/anthropic/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/anthropic/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/anthropic/storage.py
```

### 8. Run Agent that uses knowledge

Take note that claude uses OpenAI embeddings under the hood, and you will need an OpenAI API Key
```shell
export OPENAI_API_KEY=***
```

```shell
python cookbook/models/anthropic/knowledge.py
```

### 9. Run Agent that uses memory

```shell
python cookbook/models/anthropic/memory.py
```

### 10. Run Agent that analyzes an image

```shell
python cookbook/models/anthropic/image_agent.py
```

### 11. Run Agent with Thinking enabled

- Streaming on
```shell
python cookbook/models/anthropic/thinking.py
```
- Streaming off

```shell
python cookbook/models/anthropic/thinking_stream.py
```

### 12. Run Agent with Interleaved Thinking

```shell
python cookbook/models/anthropic/financial_analyst_thinking.py
```
