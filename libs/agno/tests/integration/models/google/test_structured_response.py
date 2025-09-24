import enum
from typing import Dict, List, Union

from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

from agno.agent import Agent, RunOutput  # noqa
from agno.models.google import Gemini


class SimpleMovieScript(BaseModel):
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


class MovieScriptWithDict(BaseModel):
    setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
    )
    rating: Dict[str, int] = Field(
        ...,
        description="Your own rating of the movie. 1 to 5. Return a dictionary with the keys 'story' and 'acting'.",
    )


class Rating(BaseModel):
    story: int = Field(..., description="Your own rating of the movie. 1 to 5.")
    acting: int = Field(..., description="Your own rating of the movie. 1 to 5.")


class MovieScriptWithNested(BaseModel):
    setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
    )
    rating: Rating = Field(
        ...,
        description="Your own rating of the movie. 1 to 5.",
    )


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


class UnionFieldResponse(BaseModel):
    flexible_value: Union[str, int, bool] = Field(..., description="Value that can be string, number, or boolean")
    name: str = Field(..., description="Required name field")


def test_structured_response():
    structured_output_agent = Agent(
        model=Gemini(id="gemini-2.0-flash"),
        description="You help people write movie scripts.",
        output_schema=SimpleMovieScript,
    )
    response = structured_output_agent.run("New York")
    assert response.content is not None
    assert isinstance(response.content.setting, str)
    assert isinstance(response.content.ending, str)
    assert isinstance(response.content.genre, str)
    assert isinstance(response.content.name, str)
    assert isinstance(response.content.characters, List)
    assert isinstance(response.content.storyline, str)


def test_structured_response_with_dict_fields():
    structured_output_agent = Agent(
        model=Gemini(id="gemini-2.0-flash"),
        description="You help people write movie scripts.",
        output_schema=MovieScriptWithDict,
    )
    response = structured_output_agent.run("New York")
    assert response.content is not None
    assert isinstance(response.content.rating, Dict)
    assert isinstance(response.content.setting, str)
    assert isinstance(response.content.ending, str)
    assert isinstance(response.content.genre, str)


def test_structured_response_with_nested_fields():
    structured_output_agent = Agent(
        model=Gemini(id="gemini-2.0-flash"),
        description="You help people write movie scripts.",
        output_schema=MovieScriptWithNested,
    )
    response = structured_output_agent.run("New York")
    assert response.content is not None
    assert isinstance(response.content.rating, Rating)
    assert isinstance(response.content.rating.story, int)
    assert isinstance(response.content.rating.acting, int)
    assert isinstance(response.content.setting, str)
    assert isinstance(response.content.ending, str)
    assert isinstance(response.content.genre, str)


def test_structured_response_with_enum_fields():
    structured_output_agent = Agent(
        model=Gemini(id="gemini-2.0-flash"),
        description="You help generate recipe names and ratings.",
        output_schema=Recipe,
    )
    response = structured_output_agent.run("Generate a recipe name and rating.")
    assert response.content is not None
    assert isinstance(response.content.rating, Grade)
    assert isinstance(response.content.recipe_name, str)


def test_structured_response_with_union_field_types():
    """Test structured output with Union types that exercise our union handling logic"""
    structured_output_agent = Agent(
        model=Gemini(id="gemini-2.0-flash"),
        description="You return data with flexible union-typed fields.",
        output_schema=UnionFieldResponse,
    )
    response = structured_output_agent.run(
        "Return a response with a flexible value that could be text, number, or true/false"
    )

    assert response.content is not None
    assert isinstance(response.content.name, str)
    # The flexible_value should be one of the union types
    assert isinstance(response.content.flexible_value, (str, int, bool))
