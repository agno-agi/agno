# IBM WatsonX

[Models overview](https://dataplatform.cloud.ibm.com/docs/content/wsj/analyze-data/fm-models.html?context=wx)

Supported models:

- `ibm/granite-20b-code-instruct`
- `ibm/granite-3-2b-instruct`
- `ibm/granite-3-8b-instruct`
- `meta-llama/llama-3-1-70b-instruct`
- `meta-llama/llama-3-1-8b-instruct`
- `meta-llama/llama-3-2-11b-vision-instruct`
- `meta-llama/llama-3-3-70b-instruct`
- `mistralai/mistral-large`
- `mistralai/mistral-small-24b-instruct-2501`
- `mistralai/mixtral-8x7b-instruct-v01`
- `mistralai/pixtral-12b`

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

### 3. Install libraries

```shell
pip install -U boto3 duckduckgo-search agno
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
