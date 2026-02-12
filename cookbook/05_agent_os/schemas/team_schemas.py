"""
Team Input And Output Schemas
=============================

Demonstrates AgentOS teams that use input and output schemas.
"""

from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
input_schema_db = SqliteDb(
    session_table="team_session",
    db_file="tmp/team.db",
)

output_schema_db = SqliteDb(
    session_table="research_team_sessions",
    db_file="tmp/team_output_schema.db",
)


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


class ResearchReport(BaseModel):
    """Structured research report output."""

    topic: str = Field(..., description="Research topic")
    summary: str = Field(..., description="Executive summary")
    key_findings: List[str] = Field(..., description="Key findings")
    recommendations: List[str] = Field(..., description="Action recommendations")


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
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
    db=input_schema_db,
)

web_researcher = Agent(
    name="Web Researcher",
    model=OpenAIChat(id="o3-mini"),
    tools=[WebSearchTools()],
    role="Conduct comprehensive web research",
    instructions=[
        "Search for authoritative sources and documentation",
        "Find recent articles and blog posts",
        "Gather diverse perspectives on the topics",
    ],
)

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    role="Conduct thorough research on assigned topics",
)

analyst = Agent(
    name="Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Analyze research findings and provide recommendations",
)

# ---------------------------------------------------------------------------
# Create Teams
# ---------------------------------------------------------------------------
research_team_with_input_schema = Team(
    name="Research Team with Input Validation",
    model=OpenAIChat(id="o3-mini"),
    members=[hackernews_agent, web_researcher],
    delegate_to_all_members=True,
    input_schema=ResearchProject,
    instructions=[
        "Conduct thorough research based on the validated input",
        "Coordinate between team members to avoid duplicate work",
        "Ensure research depth matches the specified level",
        "Respect the maximum sources limit",
        "Focus on recent sources if requested",
    ],
)

research_team_with_output_schema = Team(
    name="Research Team",
    id="research-team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, analyst],
    output_schema=ResearchReport,
    markdown=False,
    db=output_schema_db,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="team-schemas-demo",
    teams=[research_team_with_input_schema, research_team_with_output_schema],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="team_schemas:app", port=7777, reload=True)
