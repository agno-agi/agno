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
uv pip install -U anthropic ddgs duckdb agno
```

### 5. Run basic Agent

- Streaming on

```shell
python cookbook/92_models/vertexai/claude/basic_stream.py
```

- Streaming off

```shell
python cookbook/92_models/vertexai/claude/basic.py
```

### 6. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/92_models/vertexai/claude/tool_use.py
```

### 7. Run Agent that returns structured output

```shell
python cookbook/92_models/vertexai/claude/structured_output.py
```

### 8. Run Agent that uses storage

```shell
python cookbook/92_models/vertexai/claude/db.py
```

### 9. Run Agent that uses knowledge

Take note that claude uses OpenAI embeddings under the hood, and you will need an OpenAI API Key

```shell
export OPENAI_API_KEY=***
```

```shell
python cookbook/92_models/vertexai/claude/knowledge.py
```

### 10. Run Agent that uses memory

```shell
python cookbook/92_models/vertexai/claude/memory.py
```

### 11. Run Agent that analyzes an image

```shell
python cookbook/92_models/vertexai/claude/image_input_url.py
```

### 12. Run Agent with Thinking enabled

- Streaming on

```shell
python cookbook/92_models/vertexai/claude/thinking.py
```

- Streaming off

```shell
python cookbook/92_models/vertexai/claude/thinking_stream.py
```

### 13. Adaptive Thinking with `output_config`

For Claude 4.6 VertexAI models that support adaptive thinking, use `output_config` to control thinking depth via the `effort` parameter:

```shell
python cookbook/90_models/vertexai/claude/adaptive_thinking.py
```

```python
from agno.models.vertexai import Claude

model = Claude(
    id="claude-sonnet-4-6@20250514",
    max_tokens=4096,
    thinking={"type": "adaptive"},
    output_config={"effort": "high"},
)
```

**Valid effort values:**
- `"low"` - Most efficient, significant token savings
- `"medium"` - Balanced approach with moderate savings
- `"high"` - Default, high capability for complex reasoning
- `"max"` - Absolute maximum capability (Opus 4.6 only)
