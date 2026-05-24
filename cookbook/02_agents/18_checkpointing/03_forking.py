"""Forking a run via /continue with fork=true.

Same mechanic as ``from_checkpoint`` but non-destructive: the original run is
untouched, and a new sibling run is created with:
- a fresh ``run_id``
- ``forked_from_run_id`` set to the original
- ``forked_from_message_index`` set to the checkpoint
- the same ``session_id`` — forks are siblings within a session

Use forks to:
- Explore alternative paths from a known-good intermediate state.
- Run an eval: same starting state, different prompts, compare outcomes.
- A/B-test agent instructions or tools.

The session's ``runs`` array becomes a DAG (each fork points at its origin via
``forked_from_run_id``). Both runs are independently retrievable.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses


def get_weather(city: str) -> str:
    """Mock weather lookup."""
    data = {"Paris": "Cloudy, 14°C", "Tokyo": "Sunny, 22°C", "Lagos": "Hot, 31°C"}
    return data.get(city, "unknown")


async def main() -> None:
    agent = Agent(
        name="weather-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(
            session_table="checkpoint_demo",
            db_file="tmp/checkpoint_forking.db",
        ),
        checkpoint="steps",
        tools=[get_weather],
    )

    # Original run — agent answers about Paris.
    original = await agent.arun(input="What's the weather in Paris?")
    print("Original run")
    print("  run_id:", original.run_id)
    print("  content:", original.content)
    print()

    # Fork from index 1 (just the user question) with a different prompt.
    # The original is preserved; the fork is a new sibling.
    fork = await agent.acontinue_run(
        run_id=original.run_id,
        session_id=original.session_id,
        from_checkpoint=1,
        fork=True,
        input="What's the weather in Tokyo and Lagos?",
    )
    print("Forked run")
    print("  run_id:", fork.run_id, "(new)")
    print("  forked_from_run_id:", fork.forked_from_run_id)
    print("  forked_from_message_index:", fork.forked_from_message_index)
    print("  content:", fork.content)
    print()

    # Both runs coexist in the same session — verify with a session read.
    session = agent.db.get_session(session_id=original.session_id, session_type="agent")
    print("Session has", len(session.runs or []), "runs:")
    for r in session.runs or []:
        forked_marker = (
            f" (forked from {r.forked_from_run_id})" if r.forked_from_run_id else ""
        )
        print(f"  - {r.run_id} [{r.status}]{forked_marker}")


if __name__ == "__main__":
    asyncio.run(main())
