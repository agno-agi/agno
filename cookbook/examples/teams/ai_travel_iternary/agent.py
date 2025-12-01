from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.google_maps import GoogleMapTools
from agno.team import Team
from agno.os import AgentOS
from agno.db.sqlite import SqliteDb
from dotenv import load_dotenv
import os

load_dotenv()
google_api_key = os.getenv("GOOGLE_API_KEY")
google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")

if not google_api_key:
    raise ValueError("GOOGLE_API_KEY environment variable is required. Please set it in your .env file.")
if not google_maps_api_key:
    raise ValueError("GOOGLE_MAPS_API_KEY environment variable is required. Please set it in your .env file.")

google_tools = GoogleMapTools(key=google_maps_api_key)

os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/travel_planner.db")

navigator_agent = Agent(
    name="Navigator Agent",
    model=Gemini(id="gemini-2.0-flash-exp", api_key=google_api_key),
    tools=[google_tools],
    description="Integrates with Google Maps to deliver accurate travel times, route options, and local transport insights.",
    instructions=[
        "Always include latitude and longitude coordinates for each location",
        "Format coordinates as: Lat: XX.XXXXX, Lng: XX.XXXXX"
    ],
    markdown=True,
)

attraction_finder = Agent(
    name="Attraction Finder",
    model=Gemini(id="gemini-2.0-flash-exp", api_key=google_api_key),
    tools=[google_tools],
    description="Curates top-rated landmarks, restaurants, and experiences using live data, reviews, and current trends.",
    instructions=[
        "Always include latitude and longitude coordinates for each recommended place",
        "Format coordinates as: Lat: XX.XXXXX, Lng: XX.XXXXX",
        "Include address along with coordinates"
    ],
    markdown=True,
)

itinerary_composer = Team(
    name="Itinerary Composer Team",
    model=Gemini(id="gemini-2.0-flash-exp", api_key=google_api_key),
    members=[navigator_agent, attraction_finder],
    description="Orchestrates all agent outputs, balancing travel and rest time to produce a seamless, day-by-day plan with verified durations.",
    instructions=[
        "Coordinate between Navigator and Attraction Finder agents",
        "Create a balanced day-by-day itinerary",
        "Include travel times, rest periods, and meal breaks",
        "Ensure realistic timing and avoid over-scheduling",
        "Provide a comprehensive summary with all details",
        "Include estimated costs where possible",
        "Prioritize user preferences and constraints",
        "IMPORTANT: For every location in the itinerary, include latitude and longitude coordinates in the format: Lat: XX.XXXXX, Lng: XX.XXXXX",
        "Add coordinates in a consistent format for easy parsing and map integration"
    ],
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
    show_members_responses=True,
)

agent_os = AgentOS(
    teams=[itinerary_composer],
    agents=[navigator_agent, attraction_finder]
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent:app", port=7777) 