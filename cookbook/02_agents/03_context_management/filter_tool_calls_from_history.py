"""
Filter Tool Calls From History
=============================

Demonstrates `max_tool_calls_from_history` by showing that tool-call filtering only
affects model input history while full run history remains in storage.
"""

import random

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses


def get_weather_for_city(city: str) -> str:
    conditions = ["Sunny", "Cloudy", "Rainy", "Snowy", "Foggy", "Windy"]
    temperature = random.randint(-10, 35)
    condition = random.choice(conditions)

    return f"{city}: {temperature}°C, {condition}"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_weather_for_city],
    instructions="You are a weather assistant. Get the weather using the get_weather_for_city tool.",
    # Only keep 3 most recent tool calls from history in context (reduces token costs)
    max_tool_calls_from_history=3,
    db=SqliteDb(db_file="tmp/weather_data.db"),
    add_history_to_context=True,
    markdown=True,
    # debug_mode=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
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
