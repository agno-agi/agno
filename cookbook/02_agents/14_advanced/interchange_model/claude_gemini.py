import os

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini


def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"The weather in {city} is sunny and 22C."


def main() -> None:
    db_url = os.getenv(
        "AGNO_POSTGRES_URL",
        "postgresql+psycopg://ai:ai@localhost:5532/ai",
    )
    db = PostgresDb(db_url)

    agent = Agent(
        model=Claude(),
        db=db,
        add_history_to_context=True,
        num_history_runs=10,
        tools=[get_weather],
        debug_mode=True,
    )

    # Turn 1 — Claude with tool call
    agent.print_response("What is the weather in Paris?")

    # Turn 2 — Gemini with tool call
    agent.model = Gemini()
    agent.print_response("What is the weather in London?")

    # Turn 3 — Claude with tool call (works fine on its own)
    agent.model = Claude()
    agent.print_response("What is the weather in Tokyo?")

    # Turn 4 — Gemini summary
    agent.model = Gemini()
    agent.print_response("Summarize all the weather we checked.")


if __name__ == "__main__":
    main()
