import enum
from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.zhipu import Zhipu


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
    """Test basic structured output with MovieScript schema"""
    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        description="You help people write movie scripts",
        output_schema=MovieScript,
    )
    response = agent.run("New York")
    assert response.content is not None
    assert isinstance(response.content, MovieScript)
    assert isinstance(response.content.setting, str)
    assert isinstance(response.content.characters, List)


def test_structured_response_with_enum():
    """Test structured response with enum fields"""

    class Grade(enum.Enum):
        A_PLUS = "a+"
        A = "a"
        B = "b"
        C = "c"

    class Recipe(BaseModel):
        recipe_name: str
        rating: Grade

    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        output_schema=Recipe,
    )
    response = agent.run("Generate a recipe name and rating")
    assert response.content is not None
    assert isinstance(response.content.rating, Grade)


def test_structured_response_with_thinking():
    """Test structured response with thinking mode"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        output_schema=MovieScript,
    )
    response = agent.run("Create a sci-fi movie about time travel")
    assert response.content is not None
    assert isinstance(response.content, MovieScript)
    assert len(response.content.storyline) > 20


def test_nested_structured_response():
    """Test nested structured responses"""

    class Actor(BaseModel):
        name: str
        role: str

    class Movie(BaseModel):
        title: str
        year: int
        main_actors: List[Actor]

    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        output_schema=Movie,
    )

    response = agent.run("Tell me about Inception (2010)")
    assert response.content is not None
    assert isinstance(response.content, Movie)
    assert isinstance(response.content.main_actors, list)
    assert len(response.content.main_actors) > 0


def test_structured_response_with_optional_and_complex_types():
    """Test structured response with optional fields and complex types"""
    from typing import Dict, Optional, Union

    class Product(BaseModel):
        name: str
        price: Optional[float] = None
        tags: List[str]
        metadata: Dict[str, Union[str, int]] = Field(default_factory=dict)

    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        output_schema=Product,
    )

    response = agent.run("Tell me about iPhone 15")
    assert response.content is not None
    assert isinstance(response.content, Product)
    assert response.content.name is not None
    assert isinstance(response.content.tags, list)
    assert isinstance(response.content.metadata, dict)
