from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.v2.step import Step
from agno.workflow.v2.workflow import Workflow

# Define agents
image_analyzer = Agent(
    name="Image Analyzer",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Analyze the provided image and extract key details, objects, and context.",
)

news_researcher = Agent(
    name="News Researcher",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="Search for latest news and information related to the analyzed image content.",
)

# Define steps
analysis_step = Step(
    name="Image Analysis Step",
    agent=image_analyzer,
)

research_step = Step(
    name="News Research Step",
    agent=news_researcher,
)

# Create workflow with media input
media_workflow = Workflow(
    name="Image Analysis and Research Workflow",
    description="Analyze an image and research related news",
    steps=[analysis_step, research_step],
    storage=SqliteStorage(
        table_name="workflow_v2",
        db_file="tmp/workflow_v2.db",
        mode="workflow_v2",
    ),
)

# Run workflow with image input
if __name__ == "__main__":
    media_workflow.print_response(
        message="Please analyze this image and find related news",
        images=[
            Image(
                url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
            )
        ],
        markdown=True,
    )
