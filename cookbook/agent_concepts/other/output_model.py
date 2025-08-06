from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


def get_weather(city: str) -> str:
    return """
    The weather in Paris is sunny.
    The temperature is 20 degrees Celsius.
    The humidity is 50%.
    The wind speed is 10 km/h.
    The precipitation is 0 mm.
    The cloud cover is 0%.
    The visibility is 10 km.
    The pressure is 1013 hPa.
    The UV index is 10.
    The air quality is good.
    The air quality index is 10.
    The air quality index is 10.

    Some more facts about Paris:
    - The Eiffel Tower is 330 meters tall.
    - The Louvre Museum is the largest museum in the world.
    - The Seine River is 776 kilometers long.
    - The population of Paris is 2.1 million.
    - The area of Paris is 105 square kilometers.
    - The average temperature in Paris is 12 degrees Celsius.
    """


agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    # output_model=OpenAIChat(id="o3-mini"),
    tools=[get_weather],
)

agent.print_response("What is the weather in Paris?", stream=True)
