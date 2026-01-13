"""Use DynamoDb as the database for an agent.

Set the following environment variables to connect to your DynamoDb instance:
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_REGION

Run `pip install boto3` to install dependencies."""

from agno.agent import Agent
from agno.db import DynamoDb

# Setup the DynamoDB database
db = DynamoDb()

# Setup a basic agent with the DynamoDB database
agent = Agent(
    db=db,
    name="DynamoDB Agent",
    description="An agent that uses DynamoDB as a database",
    add_history_to_context=True,
)

# The Agent sessions and runs will now be stored in DynamoDB
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
