import asyncio
from datetime import date
from textwrap import dedent
from typing import List, Literal

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp_toolbox import MCPToolbox
from pydantic import BaseModel, Field

url = "http://127.0.0.1:5001"

toolsets = ["hotel-management", "booking-system"]


class Hotel(BaseModel):
    id: int = Field(..., description="Unique identifier for the hotel")
    name: str = Field(..., description="Name of the hotel")
    location: str = Field(..., description="Location of the hotel")
    checkin_date: date = Field(..., description="Check-in date for the hotel stay")
    checkout_date: date = Field(..., description="Check-out date for the hotel stay")
    price_tier: Literal["Luxury", "Economy", "Boutique", "Extended-Stay"] = Field(
        description="The hotel tier/category - must be one of: Luxury, Economy, Boutique, or Extended-Stay"
    )
    booked: str = Field(
        description="Indicates if the hotel is booked (bit field from database)"
    )


class HotelSearch(BaseModel):
    location: str = Field(
        ...,
        description="The city, region, or specific location to search for hotels",
        min_length=1,
        max_length=100,
    )
    tier: Literal["Luxury", "Economy", "Boutique", "Extended-Stay"] = Field(
        description="The hotel tier/category to search for"
    )


class HotelSearchResult(BaseModel):
    hotels: List[Hotel] = Field(
        description="List of hotels matching the search criteria"
    )
    total_results: int = Field(description="Total number of hotels found")


agent = Agent(
    tools=[],
    instructions=dedent(
        """ \
        You're a helpful hotel assistant. You handle hotel searching, booking and
        cancellations. When the user searches for a hotel, mention it's name, id,
        location and price tier. Always mention hotel ids while performing any
        searches. This is very important for any operations. For any bookings or
        cancellations, please provide the appropriate confirmation. Be sure to
        update checkin or checkout dates if mentioned by the user.
        Don't ask for confirmations from the user.
    """
    ),
    markdown=True,
    input_schema=HotelSearch,
    output_schema=HotelSearchResult,
    parser_model=OpenAIChat("gpt-4o-mini"),
    debug_mode=True,
    debug_level=2,
)


async def run_agent(hotel_search: HotelSearch) -> None:
    async with MCPToolbox(url=url, toolsets=toolsets) as tools:
        agent.tools = [tools]
        await agent.aprint_response(hotel_search)


if __name__ == "__main__":
    hotel_search = HotelSearch(
        location="Zurich",
        tier="Boutique",
    )

    asyncio.run(run_agent(hotel_search))
