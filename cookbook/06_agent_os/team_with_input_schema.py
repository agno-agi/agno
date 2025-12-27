"""
This example demonstrates how to use input_schema with teams for automatic
input validation and structured data handling.

The input_schema feature allows teams to automatically validate and convert
dictionary inputs into Pydantic models, ensuring type safety and data validation.
"""

from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel, Field


class ResearchProject(BaseModel):
    """Structured research project with validation requirements."""

    project_name: str = Field(description="Name of the research project")
    research_topics: List[str] = Field(
        description="List of topics to research", min_length=1
    )
    target_audience: str = Field(description="Intended audience for the research")
    depth_level: str = Field(
        description="Research depth level", pattern="^(basic|intermediate|advanced)$"
    )
    max_sources: int = Field(description="Maximum number of sources to use", default=10)
    include_recent_only: bool = Field(
        description="Whether to focus only on recent sources", default=True
    )


# Create research agents
hackernews_agent = Agent(
    name="HackerNews Researcher",
    model=OpenAIChat(id="o3-mini"),
    tools=[HackerNewsTools()],
    role="Research trending topics and discussions on HackerNews",
    instructions=[
        "Search for relevant discussions and articles",
        "Focus on high-quality posts with good engagement",
        "Extract key insights and technical details",
    ],
    db=SqliteDb(
        session_table="team_session",
        db_file="tmp/team.db",
    ),
)

web_researcher = Agent(
    name="Web Researcher",
    model=OpenAIChat(id="o3-mini"),
    tools=[DuckDuckGoTools()],
    role="Conduct comprehensive web research",
    instructions=[
        "Search for authoritative sources and documentation",
        "Find recent articles and blog posts",
        "Gather diverse perspectives on the topics",
    ],
)

# Create team with input_schema for automatic validation
research_team = Team(
    name="Research Team with Input Validation",
    model=OpenAIChat(id="o3-mini"),
    members=[hackernews_agent, web_researcher],
    delegate_to_all_members=True,  # We want all members to get the task
    input_schema=ResearchProject,
    instructions=[
        "Conduct thorough research based on the validated input",
        "Coordinate between team members to avoid duplicate work",
        "Ensure research depth matches the specified level",
        "Respect the maximum sources limit",
        "Focus on recent sources if requested",
    ],
)

agent_os = AgentOS(
    id="team-with-input-schema",
    teams=[research_team],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="team_with_input_schema:app", port=7777, reload=True)
