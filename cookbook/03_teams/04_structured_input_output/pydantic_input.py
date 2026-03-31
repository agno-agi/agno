"""
Pydantic Input
==============

Demonstrates passing validated Pydantic models as team inputs.
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel, Field


class ResearchTopic(BaseModel):
    """Structured research topic with specific requirements."""

    topic: str = Field(description="The main research topic")
    focus_areas: List[str] = Field(description="Specific areas to focus on")
    target_audience: str = Field(description="Who this research is for")
    sources_required: int = Field(description="Number of sources needed", default=5)


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
    instructions=[
        "Search Hacker News for relevant articles and discussions",
        "Extract key insights and summarize findings",
        "Focus on high-quality, well-discussed posts",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Hackernews Research Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[hackernews_agent],
    determine_input_for_members=False,
    instructions=[
        "Conduct thorough research based on the structured input",
        "Address all focus areas mentioned in the research topic",
        "Tailor the research to the specified target audience",
        "Provide the requested number of sources",
    ],
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    research_request = ResearchTopic(
        topic="AI Agent Frameworks",
        focus_areas=[
            "AI Agents",
            "Framework Design",
            "Developer Tools",
            "Open Source",
        ],
        target_audience="Software Developers and AI Engineers",
        sources_required=7,
    )

    team.print_response(input=research_request)

    alternative_research = ResearchTopic(
        topic="Distributed Systems",
        focus_areas=["Microservices", "Event-Driven Architecture", "Scalability"],
        target_audience="Backend Engineers",
        sources_required=5,
    )

    team.print_response(input=alternative_research)
