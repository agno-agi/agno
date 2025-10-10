from typing import List

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from pydantic import BaseModel, Field


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
    model=OpenAIChat(id="gpt-4o"),
    description="You write movie scripts.",
    markdown=True,
    output_schema=MovieScript,
)


# Setup your AgentOS app
agent_os = AgentOS(
    agents=[structured_agent],
    a2a_interface=True,
)
app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS with A2A interface.

    You can run the structured-output-agent via A2A protocol:
    POST http://localhost:7777/a2a/message/send
    (include "agentId": "structured-output-agent" in params.message)
    """
    agent_os.serve(app="structured_output:app", port=7777, reload=True)
