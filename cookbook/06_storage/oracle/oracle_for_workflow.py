"""Use Oracle Database as the storage backend for a Workflow.

Requires Oracle Database 19c or later. Start one locally with:
    ./cookbook/scripts/run_oracle.sh

Run `uv pip install "agno[oracle]" openai ddgs newspaper4k lxml_html_clean` to install dependencies.
"""

from agno.agent import Agent
from agno.db.oracle import OracleDb
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# On Oracle a schema is a user, so tables are created in the connecting
# user's own schema by default. See the README for how db_schema and
# create_schema behave differently here than on Postgres.
db_url = "oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1"

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
)
web_agent = Agent(
    name="Web Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[WebSearchTools()],
    role="Search the web for the latest news and trends",
)

research_team = Team(
    name="Research Team",
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)

research_step = Step(name="Research Step", team=research_team)
content_planning_step = Step(name="Content Planning Step", agent=content_planner)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation from blog posts to social media",
        db=OracleDb(session_table="workflow_session", db_url=db_url),
        steps=[research_step, content_planning_step],
    )
    content_creation_workflow.print_response(
        input="AI trends in 2024",
        markdown=True,
    )
