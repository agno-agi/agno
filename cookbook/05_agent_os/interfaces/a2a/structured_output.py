"""
Structured Output
=================

Demonstrates structured output.
"""

from typing import List

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------


class MovieScript(BaseModel):
    setting: str = Field(
        ..., description="Provide a nice setting for a blockbuster movie."
    )
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
    )
    name: str = Field(..., description="Give a name to this movie")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ..., description="3 sentence storyline for the movie. Make it exciting!"
    )


structured_agent = Agent(
    name="structured-output-agent",
    id="structured_output_agent",
    model=OpenAIChat(id="gpt-4o"),
    description="A creative AI screenwriter that generates detailed, well-structured movie scripts with compelling settings, characters, storylines, and complete plot arcs in a standardized format",
    markdown=True,
    output_schema=MovieScript,
)


# Setup your AgentOS app
agent_os = AgentOS(
    agents=[structured_agent],
    a2a_interface=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS with the A2A 1.0 interface.

    Endpoints (A2A 1.0, JSON-RPC 2.0 envelope, flat Part with mediaType):
        GET  http://localhost:7777/a2a/agents/{id}/.well-known/agent-card.json
        POST http://localhost:7777/a2a/agents/{id}/v1                 (JSON-RPC: SendMessage / SendStreamingMessage — what the a2a-sdk Client targets)
        POST http://localhost:7777/a2a/agents/{id}/v1/message:send    (legacy URL-style, kept for back-compat)
        POST http://localhost:7777/a2a/agents/{id}/v1/message:stream  (legacy URL-style, kept for back-compat)

    The structured output_schema is serialized to JSON and returned as the
    text body of the final Task's last Message part.

    Test with the official a2a-sdk client (see README.md for a runnable snippet)
    or with the a2a-inspector at https://github.com/a2aproject/a2a-inspector.
    """
    agent_os.serve(app="structured_output:app", port=7777, reload=True)
