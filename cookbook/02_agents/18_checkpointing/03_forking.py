"""Forking a run via /continue with fork=true.

Use ``continue_from="last_user"`` to choose the message boundary. The original
run is untouched and a new sibling run is created with:
- a fresh ``run_id``
- ``forked_from_run_id`` set to the original
- ``forked_from_message_index`` set to the truncation index
- the same ``session_id`` — forks live alongside their origin in one session

Use forks to:
- Explore alternative paths from a known-good intermediate state
- Run evals: same starting state, different prompts, compare outcomes
- A/B-test instructions or tools

The session's ``runs`` array becomes a DAG (each fork points at its origin via
``forked_from_run_id``).

Fork vs branch_session (see 05_branch_session.py):
- **fork**         → new run inside the **same** session (run-level)
- **branch_session** → new session containing copies of every run (session-level)

If you just want "redo the last response, keeping the old one around," the
friendlier alias is ``regenerate=True, preserve_original=True`` - same
mechanic, no message index math required. See 04_regenerate.py.
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
        checkpoint="tool-batch",
        tools=[get_weather],
    )

    original = await agent.arun(input="What's the weather in Paris?")
    print("Original run")
    print("  run_id:", original.run_id)
    print("  content:", original.content)
    print()

    # Fork from just after the last user message with a different prompt.
    # The original is preserved; the fork is a new sibling in the same session.
    fork = await agent.acontinue_run(
        run_id=original.run_id,
        session_id=original.session_id,
        continue_from="last_user",
        fork=True,
        input="What's the weather in Tokyo and Lagos?",
    )
    print("Forked run")
    print("  run_id:", fork.run_id, "(new)")
    print("  forked_from_run_id:", fork.forked_from_run_id)
    print("  forked_from_message_index:", fork.forked_from_message_index)
    print("  content:", fork.content)
    print()

    # Numeric form: fork at an exact message index. Useful when "last_user"
    # doesn't land where you want — e.g. forking from before a tool was
    # called, or right after a particular intermediate assistant turn.
    # Inspect the original transcript to pick an index:
    print("Original run transcript:")
    for i, m in enumerate(original.messages or [], start=1):
        preview = (m.content or "")[:60].replace("\n", " ")
        print(f"  [{i}] {m.role}: {preview}")
    print()

    # Fork at message index 1 (keep only the original user question), then
    # ask something completely different. This is the lower-level form
    # underlying both "last_user" and regenerate sugar.
    fork_at_index = await agent.acontinue_run(
        run_id=original.run_id,
        session_id=original.session_id,
        continue_from=1,
        fork=True,
        input="What's the weather in Sydney?",
    )
    print("Forked at index 1")
    print("  run_id:", fork_at_index.run_id, "(new)")
    print("  forked_from_run_id:", fork_at_index.forked_from_run_id)
    print("  forked_from_message_index:", fork_at_index.forked_from_message_index)
    print("  content:", fork_at_index.content)
    print()

    # All runs coexist in the same session.
    session = agent.db.get_session(session_id=original.session_id, session_type="agent")
    print(f"Session has {len(session.runs or [])} runs:")
    for r in session.runs or []:
        forked_marker = (
            f" (forked from {r.forked_from_run_id})" if r.forked_from_run_id else ""
        )
        print(f"  - {r.run_id} [{r.status}]{forked_marker}")


if __name__ == "__main__":
    asyncio.run(main())
