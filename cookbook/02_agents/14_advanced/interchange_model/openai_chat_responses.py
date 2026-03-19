import os

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat, OpenAIResponses


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
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        add_history_to_context=True,
        num_history_runs=10,
        tools=[get_weather],
        debug_mode=True,
    )

    # Turn 1 — OpenAI with tool call (works fine)
    agent.print_response("What is the weather in Paris?")

    # Turn 2 — OpenAI Responses with tool call
    agent.model = OpenAIResponses()
    agent.print_response("What is the weather in London?")

    # Turn 3 — OpenAI with tool call (works fine on its own)
    agent.model = OpenAIChat(id="gpt-4o")
    agent.print_response("What is the weather in Tokyo?")

    # Turn 4 — OpenAI Responses summary
    agent.model = OpenAIResponses()
    agent.print_response("Summarize all the weather we checked.")


if __name__ == "__main__":
    main()
