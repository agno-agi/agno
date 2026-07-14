"""
Save Workflow to Database
=========================

Demonstrates creating a workflow with multiple steps and saving it to the
database.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
# Define agents
hackernews_agent = Agent(
    id="hackernews-agent",
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Extract key insights and content from Hackernews posts",
)
web_agent = Agent(
    id="web-agent",
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Search the web for the latest news and trends",
)

# ---------------------------------------------------------------------------
# Create Workflow Steps
# ---------------------------------------------------------------------------
# Define steps
research_step = Step(
    name="Research Step",
    agent=hackernews_agent,
)

content_planning_step = Step(
    name="Content Planning Step",
    agent=web_agent,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
content_creation_workflow = Workflow(
    id="content-creation-workflow",
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    db=db,
    steps=[research_step, content_planning_step],
)

# ---------------------------------------------------------------------------
# Run Workflow Save Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Save the workflow to the database
    version = content_creation_workflow.save(db=db)
    print(f"Saved workflow as version {version}")

    # By default, saving a workflow will create a new version of the workflow

    # Delete the workflow from the database (soft delete by default)
    # content_creation_workflow.delete()

    # Hard delete (permanently removes from database)
    # content_creation_workflow.delete(hard_delete=True)
