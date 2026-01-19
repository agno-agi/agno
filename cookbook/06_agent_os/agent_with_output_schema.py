"""
Agent with output_schema - Structured Outputs

Demonstrates using output_schema with agents:
1. Agent with pre-configured output_schema (MovieScript)
2. Override the schema dynamically via API at runtime

Run: python cookbook/agent_os/agent_with_output_schema.py

Example API calls:
# Using pre-configured schema
curl -X POST http://localhost:7777/agents/movie-agent/runs \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "message=Write a sci-fi movie about AI"

# Override with different schema via API
curl -X POST http://localhost:7777/agents/movie-agent/runs \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "message=Analyze benefits of remote work" \
  -d 'output_schema={"title":"Analysis","type":"object","properties":{"summary":{"type":"string"},"pros":{"type":"array","items":{"type":"string"}},"cons":{"type":"array","items":{"type":"string"}}},"required":["summary","pros","cons"]}'
"""

from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    """Structured movie script output."""

    title: str = Field(..., description="Movie title")
    genre: str = Field(..., description="Movie genre")
    logline: str = Field(..., description="One-sentence summary")
    main_characters: List[str] = Field(..., description="Main character names")


movie_agent = Agent(
    name="Movie Script Agent",
    id="movie-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Creates structured outputs - default MovieScript format, but can be overridden",
    output_schema=MovieScript,
    markdown=False,
    db=SqliteDb(
        session_table="movie_agent_sessions",
        db_file="tmp/agent_output_schema.db",
    ),
)

agent_os = AgentOS(
    id="agent-output-schema-demo",
    agents=[movie_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent_with_output_schema:app", port=7777, reload=True)
