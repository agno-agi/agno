from typing import List

from agno.agent.agent import Agent
from agno.app.agui import AGUIApp
from agno.models.openai import OpenAIChat
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


chat_agent = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o"),
    description="You write movie scripts.",
    markdown=True,
    response_model=MovieScript,
)

agui_app = AGUIApp(
    agent=chat_agent,
    name="Basic AG-UI Agent",
    app_id="structured_output_agui_agent",
    description="A basic agent that demonstrates AG-UI protocol integration.",
)

app = agui_app.get_app()

if __name__ == "__main__":
    agui_app.serve(app="structured_output:app", port=8000, reload=True)
