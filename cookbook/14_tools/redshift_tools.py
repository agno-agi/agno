"""
Amazon Redshift Tools Example

For IAM authentication with environment variables, set:
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_SESSION_TOKEN="your-session-token"
export REDSHIFT_HOST="your-workgroup.123456789.us-east-1.redshift-serverless.amazonaws.com"
export REDSHIFT_DATABASE="dev"
"""

from agno.agent import Agent
from agno.tools.redshift import RedshiftTools

# Example 1: Standard username/password authentication
agent = Agent(
    tools=[
        RedshiftTools(
            user="your-username",
            password="your-password",
        )
    ]
)

# Example 2: IAM authentication with environment variables (Serverless)
agent_iam = Agent(
    tools=[
        RedshiftTools(
            iam=True,
        )
    ]
)

agent.print_response(
    "List the tables in the database and describe one of the tables", markdown=True
)

agent_iam.print_response("Run a query to select 1 + 1 as result", markdown=True)
