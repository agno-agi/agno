# Anthropic Claude Vertex AI

[Models overview](https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/claude)

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your environment variables

```shell
export GOOGLE_CLOUD_PROJECT=your-project-id
export CLOUD_ML_REGION=your-region
```

### 3. Authenticate your CLI

```shell
gcloud auth application-default login
```

or

### 4. Install libraries

```shell
pip install -U anthropic ddgs duckdb agno
```

### 5. Run basic Agent

- Streaming on

```shell
python cookbook/models/vertexai/claude/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/vertexai/claude/basic.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/vertexai/claude/tool_use.py
```

### 7. Run Agent that returns structured output

```shell
python cookbook/models/vertexai/claude/structured_output.py
```

### 8. Run Agent that uses storage

```shell
python cookbook/models/vertexai/claude/db.py
```

### 9. Run Agent that uses knowledge

Take note that claude uses OpenAI embeddings under the hood, and you will need an OpenAI API Key

```shell
export OPENAI_API_KEY=***
```

```shell
python cookbook/models/vertexai/claude/knowledge.py
```

### 10. Run Agent that uses memory

```shell
python cookbook/models/vertexai/claude/memory.py
```

### 11. Run Agent that analyzes an image

```shell
python cookbook/models/vertexai/claude/image_input_url.py
```

### 12. Run Agent with Thinking enabled

- Streaming on

```shell
python cookbook/models/vertexai/claude/thinking.py
```

- Streaming off

```shell
python cookbook/models/vertexai/claude/thinking_stream.py
```
