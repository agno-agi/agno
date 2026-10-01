"""
Content Pipeline Workflow
=========================

Runnable Agno implementation of the portable OSOP workflow defined in
``content-pipeline.osop``: research a topic, plan an outline, write a draft,
review it, then publish.

Demonstrates sequential Workflow execution with input-preparation functions
passing context between steps.

Try: "AI agent frameworks in 2026"
"""

import asyncio
from textwrap import dedent
from typing import AsyncIterator

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
research_agent = Agent(
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[WebSearchTools()],
    role="Search the web for current information, statistics, and sources on the topic",
)

planner_agent = Agent(
    name="Content Planner",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=[
        "Turn research findings into a structured outline with sections and key points",
        "Keep the outline focused: one clear takeaway per section",
    ],
)

writer_agent = Agent(
    name="Writer Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Write the full content draft following the provided outline",
)

reviewer_agent = Agent(
    name="Reviewer Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=[
        "Review the draft for accuracy, tone, and structure",
        "Return the final polished version of the content",
    ],
)


# ---------------------------------------------------------------------------
# Input Preparation Functions
# ---------------------------------------------------------------------------
async def prepare_input_for_planner(step_input: StepInput) -> AsyncIterator[StepOutput]:
    topic = step_input.input
    research_output = step_input.previous_step_content
    content = dedent(
        f"""\
        Create a content outline for the topic:
        <topic>
        {topic}
        </topic>

        Base the outline on this research:
        <research>
        {research_output}
        </research>\
        """
    )
    yield StepOutput(content=content)


async def prepare_input_for_writer(step_input: StepInput) -> AsyncIterator[StepOutput]:
    topic = step_input.input
    outline = step_input.previous_step_content
    content = dedent(
        f"""\
        Write the full content draft for the topic:
        <topic>
        {topic}
        </topic>

        Follow this outline:
        <outline>
        {outline}
        </outline>\
        """
    )
    yield StepOutput(content=content)


async def prepare_input_for_reviewer(step_input: StepInput) -> AsyncIterator[StepOutput]:
    draft = step_input.previous_step_content
    content = dedent(
        f"""\
        Review this draft and return the final polished version:
        <draft>
        {draft}
        </draft>\
        """
    )
    yield StepOutput(content=content)


# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(
    name="Research Step",
    agent=research_agent,
)

planning_step = Step(
    name="Planning Step",
    agent=planner_agent,
)

writing_step = Step(
    name="Writing Step",
    agent=writing_agent,
)

review_step = Step(
    name="Review Step",
    agent=reviewer_agent,
)


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
content_pipeline_workflow = Workflow(
    name="Content Pipeline Workflow",
    description="Automated content pipeline: research, plan, write, review, publish",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
    steps=[
        research_step,
        prepare_input_for_planner,
        planning_step,
        prepare_input_for_writer,
        writing_step,
        prepare_input_for_reviewer,
        review_step,
    ],
)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    content_pipeline_workflow.print_response(
        input="AI agent frameworks in 2026",
        markdown=True,
    )

    content_pipeline_workflow.print_response(
        input="AI agent frameworks in 2026",
        markdown=True,
        stream=True,
    )

    asyncio.run(
        content_pipeline_workflow.aprint_response(
            input="AI agent frameworks in 2026",
            markdown=True,
            stream=True,
        )
    )
