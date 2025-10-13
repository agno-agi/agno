"""Travel Planning Assistant - AI agent for comprehensive travel planning"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field

from shared.database import db


class TravelItinerary(BaseModel):
    """Structured travel itinerary"""

    destination: str
    duration: str
    budget_estimate: str
    best_time_to_visit: str
    flight_options: list[str] = Field(description="Flight recommendations")
    accommodation_options: list[str] = Field(description="Hotel/lodging recommendations")
    activities: list[dict[str, str]] = Field(description="Recommended activities by day")
    restaurants: list[str] = Field(description="Restaurant recommendations")
    local_tips: list[str] = Field(description="Local tips and cultural notes")
    packing_list: list[str] = Field(description="Essential items to pack")
    estimated_costs: dict[str, str] = Field(description="Breakdown of estimated costs")


travel_planner = Agent(
    id="travel-planning-assistant",
    name="Travel Planning Assistant",
    session_id="travel_planner_session",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    db=db,
    description=dedent("""\
        Your personal AI travel agent that plans comprehensive trips, finds
        the best deals, creates custom itineraries, and remembers your travel
        preferences. From flights to activities, get personalized recommendations
        based on your style and budget.\
    """),
    instructions=[
        "Remember user's travel preferences, past trips, and budget constraints",
        "Ask clarifying questions about travel dates, budget, preferences",
        "Search for flights, accommodations, and activities",
        "Consider seasonal factors and local events",
        "Create day-by-day itineraries with timing and logistics",
        "Provide budget breakdown and money-saving tips",
        "Include local cultural tips and etiquette",
        "Suggest both popular attractions and hidden gems",
        "Consider travel time and realistic pacing",
        "Provide backup options and alternatives",
        "Include practical information (visa, currency, language)",
        "Remember what user enjoyed in past trips",
    ],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    output_schema=TravelItinerary,
    markdown=True,
)
