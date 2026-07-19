"""
Parallel Basic
==============

Demonstrates running independent research steps in parallel before sequential writing and review steps.
"""

import asyncio

from agno.agent import Agent
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow import Step, Workflow
from agno.workflow.parallel import Parallel

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
researcher = Agent(name="Researcher", tools=[HackerNewsTools(), WebSearchTools()])
writer = Agent(name="Writer")
reviewer = Agent(name="Reviewer")

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_hn_step = Step(name="Research HackerNews", agent=researcher)
research_web_step = Step(name="Research Web", agent=researcher)
write_step = Step(name="Write Article", agent=writer)
review_step = Step(name="Review Article", agent=reviewer)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Content Creation Pipeline",
    steps=[
        Parallel(research_hn_step, research_web_step, name="Research Phase"),
        write_step,
        review_step,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    input_text = "Write about the latest AI developments"

    # Sync
    workflow.print_response(input_text)

    # Sync Streaming
    workflow.print_response(
        input_text,
        stream=True,
    )

    # Async
    asyncio.run(workflow.aprint_response(input_text))

    # Async Streaming
    asyncio.run(
        workflow.aprint_response(
            input_text,
            stream=True,
        )
    )
