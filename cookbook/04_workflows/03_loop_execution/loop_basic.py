"""
Loop Basic
==========

Demonstrates loop-based workflow execution with an end-condition evaluator and max-iteration guard.
"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow import Loop, Step, Workflow
from agno.workflow.types import StepOutput

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
research_agent = Agent(
    name="Research Agent",
    role="Research specialist",
    tools=[HackerNewsTools(), WebSearchTools()],
    instructions="You are a research specialist. Research the given topic thoroughly.",
    markdown=True,
)

content_agent = Agent(
    name="Content Agent",
    role="Content creator",
    instructions="You are a content creator. Create engaging content based on research.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_hackernews_step = Step(
    name="Research HackerNews",
    agent=research_agent,
    description="Research trending topics on HackerNews",
)

research_web_step = Step(
    name="Research Web",
    agent=research_agent,
    description="Research additional information from web sources",
)

content_step = Step(
    name="Create Content",
    agent=content_agent,
    description="Create content based on research findings",
)


# ---------------------------------------------------------------------------
# Define Loop Evaluator
# ---------------------------------------------------------------------------
def research_evaluator(outputs: List[StepOutput]) -> bool:
    if not outputs:
        return False

    for output in outputs:
        if output.content and len(output.content) > 200:
            print(
                f"[PASS] Research evaluation passed - found substantial content ({len(output.content)} chars)"
            )
            return True

    print("[FAIL] Research evaluation failed - need more substantial research")
    return False


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Research and Content Workflow",
    description="Research topics in a loop until conditions are met, then create content",
    steps=[
        Loop(
            name="Research Loop",
            steps=[research_hackernews_step, research_web_step],
            end_condition=research_evaluator,
            max_iterations=3,
        ),
        content_step,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    input_text = (
        "Research the latest trends in AI and machine learning, then create a summary"
    )

    # Sync
    workflow.print_response(
        input=input_text,
    )

    # Sync Streaming
    workflow.print_response(
        input=input_text,
        stream=True,
    )

    # Async
    asyncio.run(
        workflow.aprint_response(
            input=input_text,
        )
    )

    # Async Streaming
    asyncio.run(
        workflow.aprint_response(
            input=input_text,
            stream=True,
        )
    )
