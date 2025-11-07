"""
This example shows how to use the output_model parameter to specify the model that should be used to generate the final response.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

itinerary_planner = Agent(
    name="Itinerary Planner",
    model=Claude(id="claude-sonnet-4-20250514"),
    description="You help people plan amazing vacations. Use the tools at your disposal to find latest information about the destination.",
    tools=[DuckDuckGoTools()],
)

travel_expert = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[itinerary_planner],
    output_model=OpenAIChat(id="o3-mini"),
)

travel_expert.print_response("Plan a summer vacation in Paris", stream=True)
