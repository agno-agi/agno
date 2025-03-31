"""
This example demonstrates how to use the MCP protocol to coordinate a team of agents.

Prerequisites:
- Google Maps:
    - Set the environment variable `GOOGLE_MAPS_API_KEY` with your Google Maps API key.
    You can obtain the API key from the Google Cloud Console:
    https://console.cloud.google.com/projectselector2/google/maps-apis/credentials

    - You also need to activate the Address Validation API for your .
    https://console.developers.google.com/apis/api/addressvalidation.googleapis.com

"""

import asyncio
import os
from textwrap import dedent
from typing import List, Optional

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters
from pydantic import BaseModel


# Define response models
class AirbnbListing(BaseModel):
    name: str
    description: str
    address: Optional[str] = None
    price: Optional[str] = None
    dates_available: Optional[List[str]] = None
    url: Optional[str] = None


class Attraction(BaseModel):
    name: str
    description: str
    location: str
    rating: Optional[float] = None
    visit_duration: Optional[str] = None
    best_time_to_visit: Optional[str] = None


class WeatherInfo(BaseModel):
    average_temperature: str
    precipitation: str
    recommendations: str


class TravelPlan(BaseModel):
    airbnb_listings: List[AirbnbListing]
    attractions: List[Attraction]
    weather_info: Optional[WeatherInfo] = None
    suggested_itinerary: Optional[List[str]] = None


async def run_team():
    env = {
        **os.environ,
        "GOOGLE_MAPS_API_KEY": os.getenv("GOOGLE_MAPS_API_KEY"),
    }
    # Define server parameters
    airbnb_server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@openbnb/mcp-server-airbnb", "--ignore-robots-txt"],
        env=env,
    )

    maps_server_params = StdioServerParameters(
        command="npx", args=["-y", "@modelcontextprotocol/server-google-maps"], env=env
    )

    # Use AsyncExitStack to manage multiple context managers
    async with (
        MCPTools(server_params=airbnb_server_params) as airbnb_tools,
        MCPTools(server_params=maps_server_params) as maps_tools,
    ):
        # Create all agents
        airbnb_agent = Agent(
            name="Airbnb",
            role="Airbnb Agent",
            model=OpenAIChat("gpt-4o"),
            tools=[airbnb_tools],
            instructions=dedent("""\
                You are an agent that can find Airbnb listings for a given location.
            """),
            add_datetime_to_instructions=True,
        )

        maps_agent = Agent(
            name="Google Maps",
            role="Location Services Agent",
            model=OpenAIChat("gpt-4o"),
            tools=[maps_tools],
            instructions=dedent("""\
                You are an agent that helps find attractions, points of interest,
                and provides directions in travel destinations. Help plan travel
                routes and find interesting places to visit for a given location and date.
            """),
            add_datetime_to_instructions=True,
        )

        web_search_agent = Agent(
            name="Web Search",
            role="Web Search Agent",
            model=OpenAIChat("gpt-4o"),
            tools=[DuckDuckGoTools(cache_results=True)],
            instructions=dedent("""\
                You are an agent that can search the web for information.
                Search for information about a given location.
            """),
            add_datetime_to_instructions=True,
        )

        weather_search_agent = Agent(
            name="Weather Search",
            role="Weather Search Agent",
            model=OpenAIChat("gpt-4o"),
            tools=[DuckDuckGoTools()],
            instructions=dedent("""\
                You are an agent that can search the web for information.
                Search for the weather forecast for a given location and date.
            """),
            add_datetime_to_instructions=True,
        )

        # Create and run the team
        team = Team(
            name="SkyPlanner",
            mode="coordinate",
            model=OpenAIChat("gpt-4o"),
            members=[
                airbnb_agent,
                web_search_agent,
                maps_agent,
                weather_search_agent,
            ],
            instructions=[
                "First, find the best Airbnb listings for the given location.",
                "Use the Google Maps agent to identify key neighborhoods and attractions.",
                "Use the Attractions agent to find highly-rated places to visit and restaurants.",
                "Get weather information to help with packing and planning outdoor activities.",
                "Finally, plan an itinerary for the trip.",
                "Continue asking individual team members until you have ALL the information you need.",
            ],
            response_model=TravelPlan,
            show_tool_calls=True,
            markdown=True,
            show_members_responses=True,
            add_datetime_to_instructions=True,
        )

        # Execute the team's task
        await team.aprint_response(
            dedent("""\
            I want to travel to San Francisco from New York sometime in May.
            I am one person going for 2 weeks.
            Plan my travel itinerary.
            Make sure to include the best attractions, restaurants, and activities.
            Make sure to include the best flight deals.
            Make sure to include the best Airbnb listings.
            Make sure to include the weather information.\
        """)
        )


if __name__ == "__main__":
    asyncio.run(run_team())
