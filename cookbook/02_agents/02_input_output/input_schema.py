"""
Input Schema
=============================

Input Schema.
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel, Field


class ResearchTopic(BaseModel):
    """Structured research topic with specific requirements"""

    topic: str
    focus_areas: List[str] = Field(description="Specific areas to focus on")
    target_audience: str = Field(description="Who this research is for")
    sources_required: int = Field(description="Number of sources needed", default=5)


# Define agents
# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
    input_schema=ResearchTopic,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Pass a dict that matches the input schema
    hackernews_agent.print_response(
        input={
            "topic": "AI",
            "focus_areas": ["AI", "Machine Learning"],
            "target_audience": "Developers",
            "sources_required": "5",
        }
    )

    # Pass a pydantic model that matches the input schema
    hackernews_agent.print_response(
        input=ResearchTopic(
            topic="AI",
            focus_areas=["AI", "Machine Learning"],
            target_audience="Developers",
            sources_required=5,
        )
    )
