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
pip install -U anthropic ddgs agno
```

### 4. Run basic agent

- Streaming on

```shell
python cookbook/models/aws/claude/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/aws/claude/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/aws/claude/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/aws/claude/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/aws/claude/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/models/aws/claude/knowledge.py
```
