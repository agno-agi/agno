# AWS Bedrock Anthropic Claude

[Models overview](https://docs.anthropic.com/claude/docs/models-overview)

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your AWS Credentials

#### 2.A: Leverage Access and Secret Access Keys
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
    model=AwsBedrock(id="mistral.mistral-small-2402-v1:0", session=session),
    markdown=True
)
```

#### 2.B: Leverage AWS SSO Credentials
Log in through the aws sso login command to get access to your account
```shell
aws sso login
```

Leverage sso settings in the AwsBedrock object to leverage the credentials provided by sso
```python
import boto3
agent = Agent(
    model=AwsBedrock(id="mistral.mistral-small-2402-v1:0", aws_sso_auth= True),
    markdown=True
)
```


### 3. Install libraries

```shell
pip install -U boto3 ddgs agno
```

### 4. Run basic agent

- Streaming on

```shell
python cookbook/models/aws/bedrock/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/aws/bedrock/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/aws/bedrock/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/aws/bedrock/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/aws/bedrock/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/models/aws/bedrock/knowledge.py
```
