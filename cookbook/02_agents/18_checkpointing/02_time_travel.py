"""Time-travel via /continue with continue_from.

Choose a message boundary and resume from there. For a COMPLETED run this
auto-forks into a new sibling run, preserving the "1 run = 1 model loop"
contract. The source run stays intact.

Four ways to express the same intent:
- ``continue_from="end"``                     -> continue from the full transcript
- ``continue_from="last_user"``               -> symbolic boundary
- ``continue_from=K`` (int)                   -> exact message-index boundary
- ``regenerate=True``                         -> friendly sugar for last response

When to use the numeric form: when the symbolic boundaries don't land where you
want. For example, dropping the last *three* messages (a tool batch + an
assistant reply) requires a specific index — count back from
``len(run.messages)`` and pass that as ``continue_from=K``.

To discover valid indices for a run, either inspect ``run.messages`` directly
or call the checkpoint timeline endpoint (see ``07_checkpoint_endpoints.py``).
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

    # Continue from the end: this is the default. Completed runs auto-fork, so
    # the original Paris run is preserved while this follow-up becomes a sibling.
    follow_up = await agent.acontinue_run(
        run_id=first.run_id,
        session_id=first.session_id,
        continue_from="end",
        input="Now compare that with Lagos.",
    )
    print("After /continue with continue_from='end' + follow-up")
    print("  run_id:", follow_up.run_id, "(new sibling)")
    print("  forked_from_run_id:", follow_up.forked_from_run_id)
    print("  content:", follow_up.content)
    print()

    # Rewind to just after the last user message and ask something different.
    # Completed runs auto-fork, so the original Paris run is preserved.
    rewound = await agent.acontinue_run(
        run_id=first.run_id,
        session_id=first.session_id,
        continue_from="last_user",
        input="Actually, what is the population of Tokyo instead?",
    )
    print("After /continue with continue_from='last_user' + input='Tokyo'")
    print("  run_id:", rewound.run_id, "(new sibling)")
    print("  forked_from_run_id:", rewound.forked_from_run_id)
    print("  message count:", len(rewound.messages or []))
    print("  content:", rewound.content)
    print()

    # Numeric form: continue_from=K (int) addresses an exact message boundary.
    # Use this when "end" / "last_user" don't land where you need to rewind
    # to — for example, dropping the last tool batch in addition to the
    # assistant reply.
    print("Messages in first run (for picking an index):")
    for i, m in enumerate(first.messages or [], start=1):
        preview = (m.content or "")[:60].replace("\n", " ")
        print(f"  [{i}] {m.role}: {preview}")
    print()

    # Keep only the first message (the original user question) and resume with
    # a totally different prompt. Demonstrates the K=1 boundary.
    rewound_to_index = await agent.acontinue_run(
        run_id=first.run_id,
        session_id=first.session_id,
        continue_from=1,
        input="Instead, what is the population of Tokyo?",
    )
    print("After /continue with continue_from=1 (drop everything past msg 1)")
    print("  run_id:", rewound_to_index.run_id, "(new sibling)")
    print("  forked_from_run_id:", rewound_to_index.forked_from_run_id)
    print("  forked_from_message_index:", rewound_to_index.forked_from_message_index)
    print("  content:", rewound_to_index.content)
    print()

    # Verify: all paths coexist in the session.
    session = agent.db.get_session(session_id=first.session_id, session_type="agent")
    print(f"Runs in session: {len(session.runs or [])} (source preserved, forks added)")


if __name__ == "__main__":
    asyncio.run(main())
