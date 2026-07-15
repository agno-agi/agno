"""Use ScyllaDB as the database for a team.

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

Run `uv pip install openai ddgs newspaper4k lxml_html_clean agno boto3` to install the
dependencies
"""

from typing import List

import boto3

from agno.agent import Agent
from agno.db.dynamo import DynamoDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel

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
# Create Team
# ---------------------------------------------------------------------------
class Article(BaseModel):
    title: str
    summary: str
    reference_links: List[str]


hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIChat("gpt-4o"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a topic",
    tools=[WebSearchTools()],
    add_datetime_to_context=True,
)

hn_team = Team(
    name="HackerNews Team",
    model=OpenAIChat("gpt-4o"),
    members=[hn_researcher, web_searcher],
    db=db,
    instructions=[
        "First, search hackernews for what the user is asking about.",
        "Then, ask the web searcher to search for each story to get more information.",
        "Finally, provide a thoughtful and engaging summary.",
    ],
    output_schema=Article,
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    hn_team.print_response("Write an article about the top 2 stories on hackernews")
