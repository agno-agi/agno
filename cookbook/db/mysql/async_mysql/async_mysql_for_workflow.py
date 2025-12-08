"""Use Async MySQL as the database for a workflow.
Run `pip install openai duckduckgo-search sqlalchemy asyncmy agno` to install dependencies.
"""

import asyncio
import uuid
from typing import List

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.mysql import AsyncMySQLDb
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.types import WorkflowExecutionInput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel

db_url = "mysql+asyncmy://ai:ai@localhost:3306/ai"
db = AsyncMySQLDb(db_url=db_url)


class ResearchTopic(BaseModel):
    topic: str
    key_points: List[str]
    summary: str


# Create researcher agent
researcher = Agent(
    name="Researcher",
    tools=[DuckDuckGoTools()],
    instructions="Research the given topic thoroughly and provide key insights",
    output_schema=ResearchTopic,
)

# Create writer agent
writer = Agent(
    name="Writer",
    instructions="Write a well-structured blog post based on the research provided",
)


# Define the workflow
async def blog_workflow(workflow: Workflow, execution_input: WorkflowExecutionInput):
    """
    A workflow that researches a topic and writes a blog post about it.
    """
    topic = execution_input.input

    # Step 1: Research the topic
    research_result = await researcher.arun(f"Research this topic: {topic}")

    # Step 2: Write the blog post
    if research_result and research_result.content:
        blog_result = await writer.arun(
            f"Write a blog post about {topic}. Use this research: {research_result.content.model_dump_json()}"
        )
        return blog_result.content

    return "Failed to complete workflow"


# Create and run the workflow
workflow = Workflow(
    name="Blog Generator",
    steps=blog_workflow,
    db=db,
)


async def main():
    """Run the workflow with a sample topic"""
    session_id = str(uuid.uuid4())

    await workflow.aprint_response(
        input="The future of artificial intelligence",
        session_id=session_id,
        markdown=True,
    )
    session_data = await db.get_session(
        session_id=session_id, session_type=SessionType.WORKFLOW
    )
    print("\n=== SESSION DATA ===")
    print(session_data.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
