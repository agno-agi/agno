"""
Sequence Of Steps
=================

Demonstrates sequential workflow execution with sync, async, streaming, and event-streaming run modes.
"""

import asyncio
from textwrap import dedent
from typing import AsyncIterator

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.workflow import WorkflowRunEvent, WorkflowRunOutputEvent
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
)

web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    role="Search the web for the latest news and trends",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)

writer_agent = Agent(
    name="Writer Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write a blog post on the topic",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
research_team = Team(
    name="Research Team",
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(
    name="Research Step",
    team=research_team,
)

content_planning_step = Step(
    name="Content Planning Step",
    agent=content_planner,
)


async def prepare_input_for_web_search(
    step_input: StepInput,
) -> AsyncIterator[StepOutput]:
    topic = step_input.input
    content = dedent(
        f"""\
        I'm writing a blog post on the topic
        <topic>
        {topic}
        </topic>

        Search the web for atleast 10 articles\
        """
    )
    yield StepOutput(content=content)


async def prepare_input_for_writer(step_input: StepInput) -> AsyncIterator[StepOutput]:
    topic = step_input.input
    research_team_output = step_input.previous_step_content
    content = dedent(
        f"""\
        I'm writing a blog post on the topic:
        <topic>
        {topic}
        </topic>

        Here is information from the web:
        <research_results>
        {research_team_output}
        </research_results>\
        """
    )
    yield StepOutput(content=content)


# ---------------------------------------------------------------------------
# Create Workflows
# ---------------------------------------------------------------------------
content_creation_workflow = Workflow(
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
    steps=[research_step, content_planning_step],
)

blog_post_workflow = Workflow(
    name="Blog Post Workflow",
    description="Automated blog post creation from Hackernews and the web",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
    steps=[
        prepare_input_for_web_search,
        research_team,
        prepare_input_for_writer,
        writer_agent,
    ],
)


async def stream_run_events() -> None:
    events: AsyncIterator[WorkflowRunOutputEvent] = blog_post_workflow.arun(
        input="AI trends in 2024",
        markdown=True,
        stream=True,
        stream_events=True,
    )
    async for event in events:
        if event.event == WorkflowRunEvent.condition_execution_started.value:
            print(event)
            print()
        elif event.event == WorkflowRunEvent.condition_execution_completed.value:
            print(event)
            print()
        elif event.event == WorkflowRunEvent.workflow_started.value:
            print(event)
            print()
        elif event.event == WorkflowRunEvent.step_started.value:
            print(event)
            print()
        elif event.event == WorkflowRunEvent.step_completed.value:
            print(event)
            print()
        elif event.event == WorkflowRunEvent.workflow_completed.value:
            print(event)
            print()


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Sync
    content_creation_workflow.print_response(
        input="AI trends in 2024",
        markdown=True,
    )

    # Sync Streaming
    content_creation_workflow.print_response(
        input="AI trends in 2024",
        markdown=True,
        stream=True,
    )

    # Async
    asyncio.run(
        content_creation_workflow.aprint_response(
            input="AI agent frameworks 2025",
            markdown=True,
        )
    )

    # Async Streaming
    asyncio.run(
        content_creation_workflow.aprint_response(
            input="AI agent frameworks 2025",
            markdown=True,
            stream=True,
        )
    )

    # Async Run Stream Events
    asyncio.run(stream_run_events())
