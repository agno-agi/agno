"""
Structured output with the Claude Agent SDK, using a Pydantic schema.

The schema can be set on the agent, or passed per-run to override it.

Claude enforces the schema natively: the adapter sets output_format on the SDK
query and reads back the validated result, so the model is constrained and
re-prompted on mismatch rather than parsed from prose after the fact.

Note: when a schema is set, streaming yields the validated object once at the end
rather than live tokens, since the structured result is only final on completion.

Requirements:
    uv pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_output_schema.py
"""

from typing import List

from agno.agents.claude import ClaudeAgent
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    title: str = Field(..., description="Title of the movie")
    genre: str = Field(..., description="Genre of the movie")
    characters: List[str] = Field(..., description="Names of the main characters")
    plot: str = Field(..., description="One paragraph plot summary")


class Haiku(BaseModel):
    lines: List[str] = Field(..., description="The three lines of the haiku")


# ----- Schema set on the agent -----
agent = ClaudeAgent(
    name="Claude Writer",
    model="claude-sonnet-4-6",
    max_turns=3,
    output_schema=MovieScript,
)

response = agent.run("Write a movie script set in Tokyo.")

# response.content is a MovieScript instance
script = response.content
print("Title:", script.title)
print("Genre:", script.genre)
print("Characters:", ", ".join(script.characters))
print("Plot:", script.plot)

# ----- Per-run schema overrides the agent-level one -----
response = agent.run("Write a haiku about Tokyo.", output_schema=Haiku)

haiku = response.content
print()
for line in haiku.lines:
    print(line)
