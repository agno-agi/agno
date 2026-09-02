"""Use ScyllaDB as the database for a workflow.

ScyllaDB exposes a DynamoDB-compatible API (Alternator), so Agno's DynamoDb class
works with it unchanged. You just point a boto3 DynamoDB client at the Alternator
endpoint and pass it to DynamoDb via db_client.

Start ScyllaDB with Alternator enabled:

    docker run -d --name scylla \
        -p 9042:9042 -p 8000:8000 \
        scylladb/scylla:latest \
        --alternator-port 8000 \
        --alternator-write-isolation=only_rmw_uses_lwt \
        --smp 1

You must use a safe write-isolation mode (--alternator-write-isolation=only_rmw_uses_lwt as above, or
only_rmw_uses_lwt in production). Under a permissive mode (unsafe_rmw) concurrent atomic
counter updates are silently lost with no error.

Run `uv pip install agno boto3 openai ddgs` to install dependencies.
"""

import boto3

from agno.agent import Agent
from agno.db.dynamo import DynamoDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# boto3 client pointed at ScyllaDB Alternator instead of AWS DynamoDB.
client = boto3.client(
    "dynamodb",
    endpoint_url="http://localhost:8000",
    region_name="us-east-1",
    aws_access_key_id="alternator",
    aws_secret_access_key="alternator",
)

db = DynamoDb(db_client=client)

# ---------------------------------------------------------------------------
# Define agents
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="HackerNews Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from HackerNews posts",
)
web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[WebSearchTools()],
    role="Search the web for the latest news and trends",
)

# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from HackerNews and the web",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure there are 3 posts per week",
    ],
)

# ---------------------------------------------------------------------------
# Define steps
# ---------------------------------------------------------------------------
research_step = Step(
    name="Research Step",
    team=research_team,
)

content_planning_step = Step(
    name="Content Planning Step",
    agent=content_planner,
)

# ---------------------------------------------------------------------------
# Create and run workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation from blog posts to social media",
        db=db,
        steps=[research_step, content_planning_step],
    )
    content_creation_workflow.print_response(
        input="AI trends in 2024",
        markdown=True,
    )
