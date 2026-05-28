"""Time-travel via /continue with from_checkpoint.

Truncate a run's messages to an index K and resume. The run keeps the same
``run_id`` — this is a **destructive rewind in place**. The history past K
is overwritten when the run finishes.

Three ways to express the same intent:
- ``from_checkpoint=K``                       → low-level, you pick the index
- ``from_checkpoint=K, fork=True``            → non-destructive variant
  (see 03_forking.py)
- ``regenerate=True``                         → friendly sugar that auto-picks
  the index just after the last user message
  (see 04_regenerate.py)

Use raw ``from_checkpoint`` only when you need to rewind to a *specific*
intermediate index (e.g. you want to drop the last 3 tool calls, not just the
final assistant reply). For "redo the last response," use ``regenerate=True``
— it's the same mechanic but you don't have to count messages.

To inspect the message indices for a run, print ``response.messages``.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses


def get_population(city: str) -> str:
    """Mock population lookup."""
    data = {"Paris": "2.1M", "Tokyo": "13.9M", "Lagos": "15.3M"}
    return data.get(city, "unknown")


async def main() -> None:
    agent = Agent(
        name="travel-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(
            session_table="checkpoint_demo",
            db_file="tmp/checkpoint_time_travel.db",
        ),
        checkpoint="steps",
        tools=[get_population],
    )

    first = await agent.arun(input="What is the population of Paris?")
    print("First run completed")
    print("  run_id:", first.run_id)
    print("  message count:", len(first.messages or []))
    print("  content:", first.content)
    print()

    # Rewind to message index 1 (just the original user question) and ask
    # something different. Note: this is destructive — the original Paris
    # answer is overwritten in place. For a non-destructive variant pass
    # fork=True (or just use regenerate=True with additional_instructions).
    rewound = await agent.acontinue_run(
        run_id=first.run_id,
        session_id=first.session_id,
        from_checkpoint=1,
        input="Actually, what is the population of Tokyo instead?",
    )
    print("After /continue with from_checkpoint=1 + input='Tokyo'")
    print("  run_id:", rewound.run_id, "(same as before — rewind, not fork)")
    print("  message count:", len(rewound.messages or []))
    print("  content:", rewound.content)
    print()

    # Verify: the session has only ONE run. The Paris path is gone.
    session = agent.db.get_session(session_id=first.session_id, session_type="agent")
    print(f"Runs in session: {len(session.runs or [])} (Paris answer was overwritten)")


if __name__ == "__main__":
    asyncio.run(main())
