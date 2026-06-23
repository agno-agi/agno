"""
Interchange Model: All 5 Providers

Cycles through OpenAI Chat, OpenAI Responses, Claude, Gemini, and AWS Claude.
Tool calls happen on every turn, then the history is summarized from a different provider.
"""

import os
from random import randint

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.models.aws import Claude as AWSClaude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat, OpenAIResponses


def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"The weather in {city} is sunny and {randint(-10, 35)}C."


def main() -> None:
    db_url = os.getenv(
        "AGNO_POSTGRES_URL",
        "postgresql+psycopg://ai:ai@localhost:5532/ai",
    )
    db = PostgresDb(db_url)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        add_history_to_context=True,
        num_history_runs=10,
        tools=[get_weather],
        debug_mode=True,
        introduction="You are a weather agent that can check the weather in different cities.",
    )

    # Turn 1 — OpenAI Chat (call_* IDs)
    agent.print_response("What is the weather in Paris?")

    # Turn 2 — OpenAI Responses (fc_* IDs)
    agent.model = OpenAIResponses()
    agent.print_response("What is the weather in London?")

    # Turn 3 — Claude (toolu_* IDs)
    agent.model = Claude()
    agent.print_response("What is the weather in Tokyo?")

    # Turn 4 — Gemini (UUID-style IDs)
    agent.model = Gemini()
    agent.print_response("What is the weather in New York?")

    # Turn 5 — Back to OpenAI Chat to summarize all history
    agent.model = OpenAIChat(id="gpt-4o")
    agent.print_response("Summarize all the weather we checked.")

    # Turn 6 — Claude summarizes (sees history from all providers)
    agent.model = Claude()
    agent.print_response("Which city had the best weather?")

    # Turn 7 — AWS Claude
    agent.model = AWSClaude()
    agent.print_response("What is the weather in Beijing?")

    # Turn 8 — OpenAI Responses (fc_* IDs)
    agent.model = OpenAIResponses()
    agent.print_response("What is the weather in London?")


if __name__ == "__main__":
    main()
