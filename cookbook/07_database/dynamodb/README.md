# DynamoDB Integration

Examples demonstrating AWS DynamoDB integration with Agno agents.

## Setup

```shell
pip install boto3
```

## Configuration

```python
from agno.agent import Agent
from agno.db.dynamodb import DynamoDb

db = DynamoDb(
    region_name="us-east-1"
)

agent = Agent(
    db=db
)
```

## Authentication

Configure AWS credentials using one of these methods:

```shell
# Using AWS CLI
aws configure

# Using environment variables
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"
```

## Examples

- [`dynamo_for_agent.py`](dynamo_for_agent.py) - Agent with DynamoDB storage
- [`dynamo_for_team.py`](dynamo_for_team.py) - Team with DynamoDB storage
