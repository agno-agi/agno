import random

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool


@tool(stop_after_tool_call=True)
def get_weather(city: str) -> str:
    """Get the weather for a city."""
    # In a real implementation, this would call a weather API
    weather_conditions = ["sunny", "cloudy", "rainy", "snowy", "windy"]
    random_weather = random.choice(weather_conditions)

    return f"The weather in {city} is {random_weather}."


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    markdown=True,
)

agent.print_response("What can you do?", stream=True)

agent.add_tool(get_weather)

agent.print_response("What is the weather in San Francisco?", stream=True)
