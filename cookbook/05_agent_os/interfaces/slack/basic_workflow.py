"""
Basic Workflow
==============

A two-step workflow exposed through Slack: a Research Agent gathers
information, then a Content Writer turns it into a polished summary.

Key concepts:
  - ``Workflow`` chains sequential ``Step`` objects.
  - Each step uses a dedicated agent with its own model and tools.
  - Uses SQLite for session persistence (no external database required).

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Define agents for the workflow
researcher_agent = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    role="Search the web and gather comprehensive research on the given topic",
    instructions=[
        "Search for the most recent and relevant information",
        "Focus on credible sources and key insights",
        "Summarize findings clearly and concisely",
    ],
)

writer_agent = Agent(
    name="Content Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Create engaging content based on research findings",
    instructions=[
        "Write in a clear, engaging, and professional tone",
        "Structure content with proper headings and bullet points",
        "Include key insights from the research",
        "Keep content informative yet accessible",
    ],
)

# Create workflow steps
research_step = Step(
    name="Research Step",
    agent=researcher_agent,
)

writing_step = Step(
    name="Writing Step",
    agent=writer_agent,
)

# Create the workflow
workflow_db = SqliteDb(
    session_table="workflow_sessions", db_file="tmp/basic_workflow.db"
)

content_workflow = Workflow(
    name="Content Creation Workflow",
    description="Research and create content on any topic via Slack",
    db=workflow_db,
    steps=[research_step, writing_step],
)

# Create AgentOS with Slack interface for the workflow
agent_os = AgentOS(
    workflows=[content_workflow],
    interfaces=[Slack(workflow=content_workflow)],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="basic_workflow:app", reload=True)
