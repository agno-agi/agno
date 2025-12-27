"""
Team with output_schema - Structured Outputs

Demonstrates using output_schema with teams:
1. Team with pre-configured output_schema (ResearchReport)
2. Override the schema dynamically via API at runtime

Run: python cookbook/agent_os/team_with_output_schema.py

Example API calls:
# Using pre-configured schema
curl -X POST http://localhost:7777/teams/research-team/runs \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "message=Research the impact of AI on healthcare" \
  -d "stream=false"

# Override with different schema via API
curl -X POST http://localhost:7777/teams/research-team/runs \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "message=Analyze electric vehicles market" \
  -d "stream=false" \
  -d 'output_schema={"title":"MarketAnalysis","type":"object","properties":{"market_size":{"type":"string"},"trends":{"type":"array","items":{"type":"string"}},"competitors":{"type":"array","items":{"type":"string"}}},"required":["market_size","trends"]}'
"""

from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field


class ResearchReport(BaseModel):
    """Structured research report output."""

    topic: str = Field(..., description="Research topic")
    summary: str = Field(..., description="Executive summary")
    key_findings: List[str] = Field(..., description="Key findings")
    recommendations: List[str] = Field(..., description="Action recommendations")


researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    role="Conduct thorough research on assigned topics",
)

analyst = Agent(
    name="Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Analyze research findings and provide recommendations",
)


research_team = Team(
    name="Research Team",
    id="research-team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, analyst],
    output_schema=ResearchReport,
    markdown=False,
    db=SqliteDb(
        session_table="research_team_sessions",
        db_file="tmp/team_output_schema.db",
    ),
)

agent_os = AgentOS(
    id="team-output-schema-demo",
    teams=[research_team],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="team_with_output_schema:app", port=7777, reload=True)
