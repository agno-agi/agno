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
export AWS_DEFAULT_REGION=***
```

### 3. Install libraries

```shell
pip install -U boto3 duckduckgo-search duckdb yfinance agno
```

### 4. Run basic agent

- Streaming on

```shell
python cookbook/models/aws/bedrock_claude/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/aws/bedrock_claude/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/aws/bedrock_claude/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/aws/bedrock_claude/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/aws/bedrock_claude/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/models/aws/bedrock_claude/knowledge.py
```
