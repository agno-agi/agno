"""
This example shows how to set max_tool_calls_in_context to forget tool calls with history.

Run 1: 0 history + 1 current = 1 total → saves [1]
Run 2: 1 history + 1 current = 2 total → saves [1,2]
Run 3: 2 history + 1 current = 3 total → saves [1,2,3]
Run 4: 3 history + 1 current = 4 total → saves [2,3,4] (filters out 1)
Run 5: 3 history + 1 current = 4 total → saves [3,4,5] (filters out 2)
Run 6: 3 history + 1 current = 4 total → saves [4,5,6] (filters out 3)
"""

import random

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat


def get_weather_for_city(city: str) -> str:
    conditions = ["Sunny", "Cloudy", "Rainy", "Snowy", "Foggy", "Windy"]
    temperature = random.randint(-10, 35)
    condition = random.choice(conditions)

    return f"{city}: {temperature}°C, {condition}"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_weather_for_city],
    instructions="You are a weather assistant. Get the weather using the get_weather_for_city tool.",
    max_tool_calls_in_context=3,
    db=SqliteDb(db_file="tmp/weather_data.db"),
    add_history_to_context=True,
    markdown=True,
)

cities = [
    "Tokyo",
    "Delhi",
    "Shanghai",
    "São Paulo",
    "Mumbai",
    "Beijing",
    "Cairo",
    "Mexico City",
    "Osaka",
    "Karachi",
    "Dhaka",
    "Istanbul",
    "Buenos Aires",
    "Lagos",
    "Manila",
    "Rio de Janeiro",
    "Guangzhou",
    "Lahore",
    "Moscow",
    "Paris",
]

print(
    f"{'City':<20} | {'History':<8} | {'Current':<8} | {'Total in Context':<8} | {'Total in Session':<8}"
)
print("-" * 70)

for city in cities:
    run_response = agent.run(f"What's the weather in {city}?")

    # Count tool calls from history vs current
    history_tool_calls = sum(
        len(msg.tool_calls)
        for msg in run_response.messages
        if msg.role == "assistant"
        and msg.tool_calls
        and getattr(msg, "from_history", False)
    )

    current_tool_calls = sum(
        len(msg.tool_calls)
        for msg in run_response.messages
        if msg.role == "assistant"
        and msg.tool_calls
        and not getattr(msg, "from_history", False)
    )

    total_in_response = history_tool_calls + current_tool_calls

    # What's saved after filtering (get messages from session)
    saved_messages = agent.get_messages_for_session()
    saved_tool_calls = (
        sum(
            len(msg.tool_calls)
            for msg in saved_messages
            if msg.role == "assistant" and msg.tool_calls
        )
        if saved_messages
        else 0
    )

    print(
        f"{city:<20} | {history_tool_calls:<8} | {current_tool_calls:<8} | {total_in_response:<8} | {saved_tool_calls:<8}"
    )
