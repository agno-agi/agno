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
uv pip install -U anthropic ddgs duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/92_models/anthropic/basic_stream.py
```

- Streaming off

```shell
python cookbook/92_models/anthropic/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/92_models/anthropic/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/92_models/anthropic/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/92_models/anthropic/storage.py
```

### 8. Run Agent that uses knowledge

Take note that claude uses OpenAI embeddings under the hood, and you will need an OpenAI API Key
```shell
export OPENAI_API_KEY=***
```

```shell
python cookbook/92_models/anthropic/knowledge.py
```

### 9. Run Agent that uses memory

```shell
python cookbook/92_models/anthropic/memory.py
```

### 10. Run Agent that analyzes an image

```shell
python cookbook/92_models/anthropic/image_agent.py
```

### 11. Run Agent with Thinking enabled

- Streaming on
```shell
python cookbook/92_models/anthropic/thinking.py
```
- Streaming off

```shell
python cookbook/92_models/anthropic/thinking_stream.py
```

### 12. Run Agent with Interleaved Thinking

```shell
python cookbook/92_models/anthropic/financial_analyst_thinking.py
```

### 13. Adaptive Thinking with `output_config`

For Claude 4.6 models that support adaptive thinking, use `output_config` to control thinking depth via the `effort` parameter. Keep `thinking` and `output_config` as separate top-level parameters:

```shell
python cookbook/90_models/anthropic/adaptive_thinking.py
```

```python
from agno.models.anthropic import Claude

model = Claude(
    id="claude-sonnet-4-6",
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
