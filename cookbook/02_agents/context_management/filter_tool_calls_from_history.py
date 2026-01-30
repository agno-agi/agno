"""
This example demonstrates max_tool_calls_from_history to limit tool calls sent to the model.

How it works:
1. Database stores ALL runs (no limit)
2. num_history_runs loads last N runs from database (default: 3)
3. max_tool_calls_from_history filters loaded history to keep only M most recent tool calls

Flow: Database → Load History → Filter Tool Calls → Send to Model

Expected behavior (with add_history_to_context=True, no num_history_runs limit):
- Run 1: No history → Model sees: [1] → DB has: [1]
- Run 2: History [1] → Model sees: [1, 2] → DB has: [1, 2]
- Run 3: History [1,2] → Model sees: [1, 2, 3] → DB has: [1, 2, 3]
- Run 4: History [1,2,3] → Model sees: [1, 2, 3, 4] → DB has: [1, 2, 3, 4]
- Run 5: History [1,2,3,4] filtered to [2,3,4] → Model sees: [2, 3, 4, 5] → DB has: [1, 2, 3, 4, 5]
- Run 6: History [2,3,4,5] filtered to [3,4,5] → Model sees: [3, 4, 5, 6] → DB has: [1, 2, 3, 4, 5, 6]

Key insight: Filtering affects MODEL INPUT only. Database stores everything, always.
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
    # Only keep 3 most recent tool calls from history in context (reduces token costs)
    max_tool_calls_from_history=3,
    db=SqliteDb(db_file="tmp/weather_data.db"),
    add_history_to_context=True,
    markdown=True,
    # debug_mode=True,
)

cities = [
    "Tokyo",
    "Delhi",
    "Shanghai",
    "São Paulo",
    "Mumbai",
    "Beijing",
    "Cairo",
    "London",
]

print("\n" + "=" * 90)
print("Tool Call Filtering Demo: max_tool_calls_from_history=3")
print("=" * 90)
print(
    f"{'Run':<5} | {'City':<15} | {'History':<8} | {'Current':<8} | {'In Context':<11} | {'In DB':<8}"
)
print("-" * 90)


for i, city in enumerate(cities, 1):
    run_response = agent.run(f"What's the weather in {city}?")

    # Count tool calls from history (sent to model after filtering)
    history_tool_calls = sum(
        len(msg.tool_calls)
        for msg in run_response.messages
        if msg.role == "assistant"
        and msg.tool_calls
        and getattr(msg, "from_history", False)
    )

    # Count tool calls from current run
    current_tool_calls = sum(
        len(msg.tool_calls)
        for msg in run_response.messages
        if msg.role == "assistant"
        and msg.tool_calls
        and not getattr(msg, "from_history", False)
    )

    total_in_context = history_tool_calls + current_tool_calls

    # Total tool calls stored in database (unfiltered)
    saved_messages = agent.get_session_messages()
    total_in_db = (
        sum(
            len(msg.tool_calls)
            for msg in saved_messages
            if msg.role == "assistant" and msg.tool_calls
        )
        if saved_messages
        else 0
    )

    print(
        f"{i:<5} | {city:<15} | {history_tool_calls:<8} | {current_tool_calls:<8} | {total_in_context:<11} | {total_in_db:<8}"
    )
