import enum
from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.cerebras import Cerebras


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
        model=Cerebras(id="qwen-3-32b"),
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
        model=Cerebras(id="qwen-3-32b"),
        description="You help generate recipe names and ratings.",
        output_schema=Recipe,
    )
    response = structured_output_agent.run("Generate a recipe name and rating.")
    assert response.content is not None
    assert isinstance(response.content.rating, Grade)
    assert isinstance(response.content.recipe_name, str)


def test_structured_response_strict_output_false():
    """Test structured response with strict_output=False (guided mode)"""

    class MovieScriptWithDict(BaseModel):
        setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
        genre: str = Field(..., description="Genre of the movie.")
        name: str = Field(..., description="Give a name to this movie")

    guided_output_agent = Agent(
        model=Cerebras(id="qwen-3-32b", strict_output=False),
        description="You write movie scripts.",
        output_schema=MovieScriptWithDict,
    )
    response = guided_output_agent.run("Create a short action movie")
    assert response.content is not None


def test_structured_response_with_nested_objects():
    """Test structured response with nested objects - validates additionalProperties: false fix.

    This test ensures that the _ensure_additional_properties_false method correctly
    handles nested object schemas, which is required by the Cerebras API.
    """

    class Address(BaseModel):
        city: str = Field(..., description="City name")
        country: str = Field(..., description="Country name")

    class Person(BaseModel):
        name: str = Field(..., description="Person's full name")
        age: int = Field(..., description="Person's age")
        address: Address = Field(..., description="Person's address")

    agent = Agent(
        model=Cerebras(id="zai-glm-4.7"),
        description="You generate person profiles.",
        output_schema=Person,
    )
    response = agent.run("Create a profile for a 30-year-old software engineer living in San Francisco")
    assert response.content is not None
    assert isinstance(response.content.name, str)
    assert isinstance(response.content.age, int)
    assert isinstance(response.content.address, Address)
    assert isinstance(response.content.address.city, str)
    assert isinstance(response.content.address.country, str)


def test_structured_response_with_list_of_objects():
    """Test structured response with a list of objects - validates additionalProperties: false fix.

    This test ensures that array items with object types also get additionalProperties: false.
    """

    class Task(BaseModel):
        title: str = Field(..., description="Task title")
        completed: bool = Field(..., description="Whether the task is completed")

    class TodoList(BaseModel):
        name: str = Field(..., description="Name of the todo list")
        tasks: List[Task] = Field(..., description="List of tasks")

    agent = Agent(
        model=Cerebras(id="zai-glm-4.7"),
        description="You create todo lists.",
        output_schema=TodoList,
    )
    response = agent.run("Create a todo list for a weekend trip with 3 tasks")
    assert response.content is not None
    assert isinstance(response.content.name, str)
    assert isinstance(response.content.tasks, list)
    assert len(response.content.tasks) > 0
    for task in response.content.tasks:
        assert isinstance(task, Task)
        assert isinstance(task.title, str)
        assert isinstance(task.completed, bool)
