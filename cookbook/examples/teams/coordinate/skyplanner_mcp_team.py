"""
This example demonstrates how to use the MCP protocol to coordinate a team of agents.

Prerequisites:
- Google Maps:
    - Set the environment variable `GOOGLE_MAPS_API_KEY` with your Google Maps API key.
    You can obtain the API key from the Google Cloud Console:
    https://console.cloud.google.com/projectselector2/google/maps-apis/credentials

    - You also need to activate the Address Validation API for your .
    https://console.developers.google.com/apis/api/addressvalidation.googleapis.com

- Apify:
    - Set the environment variable `APIFY_TOKEN` with your Apify API token.
    You can obtain the API key from the Apify Console:
    https://console.apify.com/settings/integrations

"""

import asyncio
import os
from textwrap import dedent
from typing import List, Optional
from contextlib import AsyncExitStack

from mcp import StdioServerParameters

from agno.agent import Agent
from agno.models.google.gemini import Gemini
from agno.models.openai.chat import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.mcp import MCPTools
from pydantic import BaseModel


async def run_team():
    env = {
        **os.environ,
        "GOOGLE_MAPS_API_KEY": os.getenv("GOOGLE_MAPS_API_KEY"),
        "APIFY_TOKEN": os.getenv("APIFY_TOKEN")
    }
    # Define server parameters
    airbnb_server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@openbnb/mcp-server-airbnb", "--ignore-robots-txt"],
        env=env
    )
    
    maps_server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-google-maps"],
        env=env
    )
    
    flight_deal_server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@apify/actors-mcp-server", "--actors", "canadesk/google-flights"],
        env=env
    )
    
    # Use AsyncExitStack to manage multiple context managers
    async with (MCPTools(server_params=airbnb_server_params) as airbnb_tools, 
                MCPTools(server_params=maps_server_params) as maps_tools,
                MCPTools(server_params=flight_deal_server_params) as flight_deal_tools):
        
        # Create all agents
        airbnb_agent = Agent(
            name="Airbnb",
            role="Airbnb Agent",
            model=OpenAIChat("gpt-4o"),
            tools=[airbnb_tools],
            instructions=dedent("""\
                You are an agent that can find Airbnb listings for a given location.
            """),
        )
        
        maps_agent = Agent(
            name="Google Maps",
            role="Location Services Agent",
            model=OpenAIChat("gpt-4o"),
            tools=[maps_tools],
            instructions=dedent("""\
                You are an agent that helps find attractions, points of interest, 
                and provides directions in travel destinations. Help plan travel 
                routes and find interesting places to visit in Tokyo, Japan.
            """),
        )
        
        flight_deal_agent = Agent(
            name="Flight Deal",
            role="Flight Deal Agent",
            model=OpenAIChat("gpt-4o"),
            tools=[flight_deal_tools],
            instructions=dedent("""\
                You are an agent that can find flight deals for a given location and date.
            """),
        )
        
        # Agents that don't use MCP don't need context managers
        web_search_agent = Agent(
            name="Web Search",
            role="Web Search Agent",
            model=OpenAIChat("gpt-4o"),
            tools=[DuckDuckGoTools(cache_results=True)],
            instructions=dedent("""\
                You are an agent that can search the web for information.
                Search for information about a given location.
            """),
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
        )
        
        # Define your models
        class FlightDeal(BaseModel):
            description: str
            location: str
            price: Optional[str] = None
            url: Optional[str] = None

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
            flight_deals: List[FlightDeal]
            airbnb_listings: List[AirbnbListing]
            attractions: List[Attraction]
            weather_info: Optional[WeatherInfo] = None
            suggested_itinerary: Optional[List[str]] = None
        
        # Create and run the team
        team = Team(
            name="SkyPlanner",
            mode="coordinate",
            model=OpenAIChat("o3-mini"),
            members=[airbnb_agent, flight_deal_agent, web_search_agent, maps_agent, weather_search_agent],
            success_criteria="You have flight deals, Airbnb listings, attractions, weather information, and a suggested itinerary.",
            instructions=[
                "First, find the best flight deals for a given location and date.",
                "Then, find the best Airbnb listings for the given location.",
                "Use the Google Maps agent to identify key neighborhoods and attractions.",
                "Use the Attractions agent to find highly-rated places to visit and restaurants.",
                "Get weather information to help with packing and planning outdoor activities.",
                "Finally, plan an itinerary for the trip.",
                "Continue asking individual team members until you have ALL the information you need."
            ],
            response_model=TravelPlan,
            show_tool_calls=True,
            markdown=True,
            debug_mode=True,
            show_members_responses=True,
        )
        
        # Execute the team's task
        await team.aprint_response("""I want to travel to Tokyo, Japan sometime in May. I am one person going for 2 weeks. Plan my travel itinerary.
        Make sure to include the best attractions, restaurants, and activities.
        Make sure to include the best flight deals.
        Make sure to include the best Airbnb listings.
        Make sure to include the weather information.
        """)

if __name__ == "__main__":
    asyncio.run(run_team())

