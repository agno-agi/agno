"""Use DynamoDb as the database for an agent.

Set the following environment variables to connect to your DynamoDb instance:
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_REGION

Run `pip install boto3` to install dependencies."""

from agno.agent import Agent
from agno.db.dynamo import DynamoDb

db = DynamoDb()

agent = Agent(
    db=db,
    enable_user_memories=True,
)

agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
