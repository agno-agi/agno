import asyncio
import random
import uuid

from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.storage.postgres import PostgresStorage
from agno.team.team import Team
from agno.tools.reasoning import ReasoningTools

users = [
    "abel@example.com",
    "ben@example.com",
    "charlie@example.com",
    "dave@example.com",
    "edward@example.com",
]

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


db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent_storage = PostgresStorage(
    table_name="agent_sessions", db_url=db_url, auto_upgrade_schema=True
)

team_storage = PostgresStorage(
    table_name="team_sessions", db_url=db_url, auto_upgrade_schema=True
)

memory_db = PostgresMemoryDb(table_name="memory", db_url=db_url)
memory = Memory(db=memory_db)


def get_weather(city: str) -> str:
    return f"The weather in {city} is sunny."


def get_activities(city: str) -> str:
    activities = [
        "hiking",
        "biking",
        "swimming",
        "kayaking",
        "museum visits",
        "shopping",
        "sightseeing",
        "cafe hopping",
        "theater",
        "picnicking",
    ]
    selected_activities = random.sample(activities, k=3)
    return f"The activities in {city} are {', '.join(selected_activities)}."


weather_agent = Agent(
    agent_id="weather_agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="You are a helpful assistant that can answer questions about the weather.",
    instructions="Be concise, reply with one sentence.",
    tools=[get_weather],
    memory=memory,
    storage=agent_storage,
    add_history_to_messages=True,
)

activities_agent = Agent(
    agent_id="activities_agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="You are a helpful assistant that can answer questions about activities in a city.",
    instructions="Be concise, reply with one sentence.",
    tools=[get_activities],
    memory=memory,
    storage=agent_storage,
    add_history_to_messages=True,
)

team = Team(
    members=[weather_agent, activities_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Be concise, reply with one sentence.",
    memory=memory,
    storage=team_storage,
    markdown=True,
    enable_user_memories=True,
    add_history_to_messages=True,
)


async def run_team():
    async def run_team_for_user(user: str):
        random_city = random.choice(cities)
        await team.arun(
            message=f"I love {random_city}! What activities and weather can I expect in {random_city}?",
            user_id=user,
            session_id=f"session_{uuid.uuid4()}",
        )

    tasks = []

    # Run all 5 users concurrently
    for user in users:
        tasks.append(run_team_for_user(user))

    await asyncio.gather(*tasks)

    print("Team memory runs:", sum(len(runs) for runs in team.memory.runs.values()))
    print("Team memory memories:", len(team.memory.memories))

    return "Successfully ran team"


team_response_with_memory_impact = PerformanceEval(
    name="Team Memory Impact",
    func=run_team,
    num_iterations=5,
    warmup_runs=0,
    measure_runtime=False,
    debug_mode=True,
    memory_growth_tracking=True,
    top_n_memory_allocations=10,
)

if __name__ == "__main__":
    asyncio.run(
        team_response_with_memory_impact.arun(print_results=True, print_summary=True)
    )
