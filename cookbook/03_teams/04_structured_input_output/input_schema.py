"""
Input Schema
============

Demonstrates team-level automatic input validation using input_schema.
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team, TeamMode
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel, Field


class ResearchProject(BaseModel):
    """Structured research project with validation requirements."""

    project_name: str = Field(description="Name of the research project")
    research_topics: List[str] = Field(
        description="List of topics to research", min_items=1
    )
    target_audience: str = Field(description="Intended audience for the research")
    depth_level: str = Field(
        description="Research depth level", pattern="^(basic|intermediate|advanced)$"
    )
    max_sources: int = Field(
        description="Maximum number of sources to use", ge=3, le=20, default=10
    )
    include_recent_only: bool = Field(
        description="Whether to focus only on recent sources", default=True
    )


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="HackerNews Researcher",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[HackerNewsTools()],
    role="Research trending topics and discussions on HackerNews",
    instructions=[
        "Search for relevant discussions and articles",
        "Focus on high-quality posts with good engagement",
        "Extract key insights and technical details",
    ],
)

web_researcher = Agent(
    name="Web Researcher",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[WebSearchTools()],
    role="Conduct comprehensive web research",
    instructions=[
        "Search for authoritative sources and documentation",
        "Find recent articles and blog posts",
        "Gather diverse perspectives on the topics",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
research_team = Team(
    name="Research Team with Input Validation",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[hackernews_agent, web_researcher],
    mode=TeamMode.broadcast,
    input_schema=ResearchProject,
    instructions=[
        "Conduct thorough research based on the validated input",
        "Coordinate between team members to avoid duplicate work",
        "Ensure research depth matches the specified level",
        "Respect the maximum sources limit",
        "Focus on recent sources if requested",
    ],
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Example 1: Valid Dictionary Input (will be auto-validated) ===")
    research_team.print_response(
        input={
            "project_name": "AI Framework Comparison 2024",
            "research_topics": ["LangChain", "CrewAI", "AutoGen", "Agno"],
            "target_audience": "AI Engineers and Developers",
            "depth_level": "intermediate",
            "max_sources": 15,
            "include_recent_only": True,
        }
    )

    print("\n=== Example 2: Pydantic Model Input (direct pass-through) ===")
    research_request = ResearchProject(
        project_name="Blockchain Development Tools",
        research_topics=["Ethereum", "Solana", "Web3 Libraries"],
        target_audience="Blockchain Developers",
        depth_level="advanced",
        max_sources=12,
        include_recent_only=False,
    )

    research_team.print_response(input=research_request)
