"""
This is an example that uses the [scenario](https://github.com/langwatch/scenario) testing library to test an agent.

Prerequisites:
- Install scenario: `pip install scenario`
"""

import pytest
from scenario import Scenario, TestingAgent, scenario_cache

Scenario.configure(testing_agent=TestingAgent(model="openai/gpt-4o-mini"))


@pytest.mark.agent_test
@pytest.mark.asyncio
async def test_vegetarian_recipe_agent():
    agent = VegetarianRecipeAgent()

    def vegetarian_recipe_agent(message, context):
        # Call your agent here
        return agent.run(message)

    # Define the scenario
    scenario = Scenario(
        "User is looking for a dinner idea",
        agent=vegetarian_recipe_agent,
        success_criteria=[
            "Recipe agent generates a vegetarian recipe",
            "Recipe includes a list of ingredients",
            "Recipe includes step-by-step cooking instructions",
        ],
        failure_criteria=[
            "The recipe is not vegetarian or includes meat",
            "The agent asks more than two follow-up questions",
        ],
    )

    # Run the scenario and get results
    result = await scenario.run()

    # Assert for pytest to know whether the test passed
    assert result.success


# Example agent implementation
from agno.agent import Agent  # noqa: E402
from agno.models.openai import OpenAIChat  # noqa: E402


class VegetarianRecipeAgent:
    def __init__(self):
        self.history = []

    @scenario_cache()
    def run(self, message: str):
        self.history.append({"role": "user", "content": message})

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            markdown=True,
            instructions="You are a vegetarian recipe agent",
        )

        response = agent.run(message)
        result = response.content
        print(result)
        self.history.append(result)

        return {"message": result}
