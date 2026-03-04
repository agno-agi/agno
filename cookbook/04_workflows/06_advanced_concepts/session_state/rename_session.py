"""
Rename Session
==============

Demonstrates auto-generating a workflow session name after a run.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    instructions="Research the given topic and provide key facts and insights.",
)

writer = Agent(
    name="Writing Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Write a comprehensive article based on the research provided. Make it engaging and well-structured.",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(
    name="research",
    agent=researcher,
    description="Research the topic and gather information",
)

writing_step = Step(
    name="writing",
    agent=writer,
    description="Write an article based on the research",
)

article_creation_sequence = Steps(
    name="article_creation",
    description="Complete article creation workflow from research to writing",
    steps=[research_step, writing_step],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    article_workflow = Workflow(
        description="Automated article creation from research to writing",
        steps=[article_creation_sequence],
        db=SqliteDb(db_file="tmp/workflows.db"),
        debug_mode=True,
    )

    article_workflow.print_response(
        input="Write an article about the benefits of renewable energy",
        markdown=True,
    )

    article_workflow.set_session_name(autogenerate=True)
    print(f"New session name: {article_workflow.get_session_name()}")
