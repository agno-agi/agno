"""
Image Input
===========

Demonstrates passing image media into workflow runs and chaining analysis with follow-up research.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
image_analyzer = Agent(
    name="Image Analyzer",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Analyze the provided image and extract key details, objects, and context.",
)

news_researcher = Agent(
    name="News Researcher",
    model=OpenAIChat(id="gpt-4o"),
    tools=[WebSearchTools()],
    instructions="Search for latest news and information related to the analyzed image content.",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
analysis_step = Step(
    name="Image Analysis Step",
    agent=image_analyzer,
)

research_step = Step(
    name="News Research Step",
    agent=news_researcher,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
media_workflow = Workflow(
    name="Image Analysis and Research Workflow",
    description="Analyze an image and research related news",
    steps=[analysis_step, research_step],
    db=SqliteDb(session_table="workflow_session", db_file="tmp/workflow.db"),
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    media_workflow.print_response(
        input="Please analyze this image and find related news",
        images=[
            Image(
                url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
            )
        ],
        markdown=True,
    )
