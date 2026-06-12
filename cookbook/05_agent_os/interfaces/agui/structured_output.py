"""
Structured Output
=================

Demonstrates structured output.
"""

from typing import List

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------


class MovieScript(BaseModel):
    setting: str = Field(..., description="Setting for the movie.")
    ending: str = Field(..., description="How the movie ends.")
    genre: str = Field(..., description="Genre, e.g. action or thriller.")
    name: str = Field(..., description="Name of the movie.")
    characters: List[str] = Field(..., description="Main characters.")
    storyline: str = Field(..., description="A 3-sentence storyline.")


chat_agent = Agent(
    name="Output Schema Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    description="You write movie scripts.",
    markdown=True,
    output_schema=MovieScript,
)


# Setup your AgentOS app
agent_os = AgentOS(
    agents=[chat_agent],
    interfaces=[AGUI(agent=chat_agent)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:9001/config

    """

    agent_os.serve(app="structured_output:app", port=9001, reload=True)
