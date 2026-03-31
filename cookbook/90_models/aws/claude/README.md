# AWS Bedrock Anthropic Claude

[Models overview](https://docs.anthropic.com/claude/docs/models-overview)

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your AWS Credentials

```shell
export AWS_ACCESS_KEY_ID=***
export AWS_SECRET_ACCESS_KEY=***
export AWS_REGION=***
```

Alternatively, you can use an AWS profile:

```python
import boto3
session = boto3.Session(profile_name='MY-PROFILE')
agent = Agent(
    model=Claude(id="anthropic.claude-3-5-sonnet-20240620-v1:0", session=session),
    markdown=True
)
```

### 3. Install libraries

```shell
uv pip install -U anthropic ddgs agno
```

### 4. Run basic agent

- Streaming on

```shell
python cookbook/92_models/aws/claude/basic_stream.py
```

- Streaming off

```shell
python cookbook/92_models/aws/claude/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/92_models/aws/claude/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/92_models/aws/claude/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/92_models/aws/claude/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/92_models/aws/claude/knowledge.py
```

### 9. Adaptive Thinking with `output_config`

For Claude 4.6 Bedrock models that support adaptive thinking, use `output_config` to control thinking depth via the `effort` parameter:

```shell
python cookbook/90_models/aws/claude/adaptive_thinking.py
```

```python
from agno.models.aws import Claude

model = Claude(
    id="anthropic.claude-sonnet-4-6-20250514-v1:0",
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
