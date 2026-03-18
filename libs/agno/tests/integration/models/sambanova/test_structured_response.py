import enum
from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.sambanova import Sambanova


class MovieScript(BaseModel):
    setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
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
    storyline: str = Field(..., description="3 sentence storyline for the movie. Make it exciting!")


def test_structured_response():
    structured_output_agent = Agent(
        model=Sambanova(id="Meta-Llama-3.3-70B-Instruct"),
        description="You help people write movie scripts.",
        output_schema=MovieScript,
    )
    response = structured_output_agent.run("New York")
    assert response.content is not None
    assert isinstance(response.content.setting, str)
    assert isinstance(response.content.ending, str)
    assert isinstance(response.content.genre, str)
    assert isinstance(response.content.name, str)
    assert isinstance(response.content.characters, List)
    assert isinstance(response.content.storyline, str)


def test_structured_response_with_enum_fields():
    class Grade(enum.Enum):
        A_PLUS = "a+"
        A = "a"
        B = "b"
        C = "c"
        D = "d"
        F = "f"

    class Recipe(BaseModel):
        recipe_name: str
        rating: Grade

    structured_output_agent = Agent(
        model=Sambanova(id="Meta-Llama-3.3-70B-Instruct"),
        description="You help generate recipe names and ratings.",
        output_schema=Recipe,
    )
    response = structured_output_agent.run("Generate a recipe name and rating.")
    assert response.content is not None
    assert isinstance(response.content.rating, Grade)
    assert isinstance(response.content.recipe_name, str)


def test_structured_response_strict_output_false():
    """Test structured response with strict_output=False (guided mode)"""
    guided_output_agent = Agent(
        model=Sambanova(id="Meta-Llama-3.1-8B-Instruct", strict_output=False),
        description="You write movie scripts.",
        output_schema=MovieScript,
    )
    response = guided_output_agent.run("Create a short action movie")
    assert response.content is not None
