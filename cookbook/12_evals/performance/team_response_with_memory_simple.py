import asyncio
import random

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat
from agno.team.team import Team

cities = [
    "New York",
    "Los Angeles",
    "Chicago",
    "Houston",
    "Miami",
    "San Francisco",
    "Seattle",
    "Boston",
    "Washington D.C.",
    "Atlanta",
    "Denver",
    "Las Vegas",
]


# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)


def get_weather(city: str) -> str:
    return f"The weather in {city} is sunny."


weather_agent = Agent(
    id="weather_agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Weather Agent",
    description="You are a helpful assistant that can answer questions about the weather.",
    instructions="Be concise, reply with one sentence.",
    tools=[get_weather],
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
)

team = Team(
    members=[weather_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Be concise, reply with one sentence.",
    db=db,
    markdown=True,
    enable_user_memories=True,
    add_history_to_context=True,
)


async def run_team():
    random_city = random.choice(cities)
    _ = team.arun(
        input=f"I love {random_city}! What weather can I expect in {random_city}?",
        stream=True,
        stream_events=True,
    )

    return "Successfully ran team"


team_response_with_memory_impact = PerformanceEval(
    name="Team Memory Impact",
    func=run_team,
    num_iterations=5,
    warmup_runs=0,
    measure_runtime=False,
    debug_mode=True,
    memory_growth_tracking=True,
)

if __name__ == "__main__":
    asyncio.run(
        team_response_with_memory_impact.arun(print_results=True, print_summary=True)
    )
