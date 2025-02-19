from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai.chat import OpenAIChat  # noqa


def test_structured_output_parsing_with_quotes():
    class MovieScript(BaseModel):
        script: str = Field(..., description="The script of the movie.")
        name: str = Field(..., description="Give a name to this movie")
        characters: List[str] = Field(..., description="Name of characters for this movie.")

    movie_agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        description="You help people write movie scripts. Always add some example dialog in your scripts in double quotes.",
        response_model=MovieScript,
    )

    # Get the response in a variable
    response: RunResponse = movie_agent.run("New York")
    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.script is not None
    assert response.content.name is not None
    assert response.content.characters is not None
