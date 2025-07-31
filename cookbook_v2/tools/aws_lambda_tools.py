"""Run `pip install openai boto3` to install dependencies."""

from agno.agent import Agent
from agno.tools.aws_lambda import AWSLambdaTools

# Create an Agent with the AWSLambdaTool
agent = Agent(
    tools=[AWSLambdaTools(region_name="us-east-1")],
    name="AWS Lambda Agent",
    show_tool_calls=True,
)

# Example 1: List all Lambda functions
agent.print_response("List all Lambda functions in our AWS account", markdown=True)

# Example 2: Invoke a specific Lambda function
agent.print_response(
    "Invoke the 'hello-world' Lambda function with an empty payload", markdown=True
)

# Note: Make sure you have the necessary AWS credentials set up in your environment
# or use AWS CLI's configure command to set them up before running this script.
