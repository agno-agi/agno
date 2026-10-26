from typing import List, Optional

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.togetherlink import TogetherLink
from agno.run.base import RunStatus


class City(BaseModel):
    name: str = Field(..., description="City name")
    country: str = Field(..., description="Country the city is in")
    population_millions: float = Field(..., description="Approximate population in millions")


class Trip(BaseModel):
    title: str
    cities: List[City] = Field(..., description="Between two and three cities to visit")
    budget_usd: Optional[int] = Field(None, description="Rough budget in USD, if known")


def get_population(city: str) -> str:
    """Get the population of a city in millions.

    Args:
        city: Name of the city.
    """
    return f"{city} has a population of 9.99 million."


@pytest.mark.parametrize(
    "model_id", ["auto", "moonshotai/Kimi-K3", "zai-org/GLM-5.3-Flash", "deepseek-ai/DeepSeek-V4.1-Flash"]
)
def test_structured_output(model_id):
    agent = Agent(model=TogetherLink(id=model_id), output_schema=City, telemetry=False)

    response = agent.run("Describe the largest city in Japan.")

    assert response.status == RunStatus.completed
    assert isinstance(response.content, City)
    assert response.content.country.strip().lower() == "japan"
    assert "tokyo" in response.content.name.lower()


def test_structured_output_values_are_consistent_across_runs():
    """Values, not just shape: every field must hold the right kind of content on repeated runs."""
    agent = Agent(model=TogetherLink(id="zai-org/GLM-5.3-Flash"), output_schema=City, telemetry=False)

    for _ in range(3):
        response = agent.run("Describe the largest city in Japan.")
        assert isinstance(response.content, City)
        assert response.content.country.strip().lower() == "japan"
        assert len(response.content.name) < 40


def test_structured_output_with_tools_via_parser_model():
    """With tools and output_schema together, gateway models tend to answer in JSON without calling
    the tool. A parser_model lets the main model use tools freely, then structures the final answer."""
    agent = Agent(
        model=TogetherLink(id="zai-org/GLM-5.3-Flash"),
        tools=[get_population],
        output_schema=City,
        parser_model=TogetherLink(id="deepseek-ai/DeepSeek-V4.1-Flash"),
        telemetry=False,
    )

    response = agent.run("Use the tool to get the population of Berlin, then describe Berlin.")

    assert response.status == RunStatus.completed
    assert "get_population" in [t.tool_name for t in response.tools or []]
    assert isinstance(response.content, City)
    assert response.content.population_millions == pytest.approx(9.99, abs=0.01)


def test_nested_structured_output():
    agent = Agent(model=TogetherLink(id="moonshotai/Kimi-K3"), output_schema=Trip, telemetry=False)

    response = agent.run("Plan a short trip through Italy.")

    assert isinstance(response.content, Trip)
    assert 2 <= len(response.content.cities) <= 3
    assert all(isinstance(c, City) for c in response.content.cities)


def test_structured_output_json_mode():
    agent = Agent(
        model=TogetherLink(id="deepseek-ai/DeepSeek-V4.1-Flash"),
        output_schema=City,
        use_json_mode=True,
        telemetry=False,
    )

    response = agent.run("Describe the capital of France.")

    assert isinstance(response.content, City)
    assert response.content.name.lower() == "paris"


def test_structured_output_stream():
    agent = Agent(model=TogetherLink(id="deepseek-ai/DeepSeek-V4.1-Flash"), output_schema=City, telemetry=False)

    final = None
    for event in agent.run("Describe the capital of Germany.", stream=True):
        if isinstance(event.content, City):
            final = event.content

    assert final is not None
    assert final.name.lower() == "berlin"


@pytest.mark.asyncio
async def test_async_structured_output():
    agent = Agent(model=TogetherLink(id="deepseek-ai/DeepSeek-V4.1-Flash"), output_schema=City, telemetry=False)

    response = await agent.arun("Describe the capital of Spain.")

    assert isinstance(response.content, City)
    assert response.content.name.lower() == "madrid"
