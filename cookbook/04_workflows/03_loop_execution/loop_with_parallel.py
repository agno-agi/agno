"""
Loop With Parallel
==================

Demonstrates a loop body that mixes `Parallel` and sequential steps before final content generation.
"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow import Loop, Parallel, Step, Workflow
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

analysis_agent = Agent(
    name="Analysis Agent",
    role="Data analyst",
    instructions="You are a data analyst. Analyze and summarize research findings.",
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

trend_analysis_step = Step(
    name="Trend Analysis",
    agent=analysis_agent,
    description="Analyze trending patterns in the research",
)

sentiment_analysis_step = Step(
    name="Sentiment Analysis",
    agent=analysis_agent,
    description="Analyze sentiment and opinions from the research",
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

    total_content_length = sum(len(output.content or "") for output in outputs)
    if total_content_length > 500:
        print(
            f"[PASS] Research evaluation passed - found substantial content ({total_content_length} chars total)"
        )
        return True

    print(
        f"[FAIL] Research evaluation failed - need more substantial research (current: {total_content_length} chars)"
    )
    return False


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Advanced Research and Content Workflow",
    description="Research topics with parallel execution in a loop until conditions are met, then create content",
    steps=[
        Loop(
            name="Research Loop with Parallel Execution",
            steps=[
                Parallel(
                    research_hackernews_step,
                    research_web_step,
                    trend_analysis_step,
                    name="Parallel Research & Analysis",
                    description="Execute research and analysis in parallel for efficiency",
                ),
                sentiment_analysis_step,
            ],
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

    # Async Streaming
    asyncio.run(
        workflow.aprint_response(
            input=input_text,
            stream=True,
        )
    )
