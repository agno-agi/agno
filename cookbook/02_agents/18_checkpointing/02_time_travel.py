"""Time-travel via /continue with from_checkpoint.

The ``from_checkpoint`` parameter on ``/continue`` truncates a run's messages
to a given index, prunes tool executions that no longer have references, then
resumes. The run keeps the same ``run_id`` — this is a rewind in place, not a
fork. (For a non-destructive rewind, see ``03_forking.py``.)

Typical use:
- An eval/research agent went down a wrong path. Rewind to before the wrong
  turn, supply different guidance via ``input=``, and try again.
- A bug in a tool poisoned the message history. Rewind past it.
- Reproduce a specific intermediate state for debugging.

The message index counts ALL messages in the run, including system/user/tool
messages — not just the assistant turns. Inspect ``response.messages`` to pick
the right K.
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

    # First run — agent answers a question about Paris.
    first = await agent.arun(input="What is the population of Paris?")
    print("First run completed")
    print("  run_id:", first.run_id)
    print("  message count:", len(first.messages or []))
    print("  content:", first.content)
    print()

    # Rewind to message index 1 (just the original user question, before the
    # assistant's tool call and answer). Then ask a different question via
    # input="...". The run continues with a fresh path from index 1.
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


if __name__ == "__main__":
    asyncio.run(main())
