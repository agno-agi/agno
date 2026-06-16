"""Time-travel a team run via `continue_from`.

``continue_from`` chooses the message boundary to resume from. Three forms:
- ``continue_from="end"``          full transcript (default)
- ``continue_from="last_user"``    just after the latest user message
- ``continue_from=K`` (int)        exact message-index boundary

For a COMPLETED team run, /continue auto-forks into a new sibling run so the
source run remains a durable record of the completed model loop.

Related variants:
- Pair with ``fork=True`` to make the fork explicit (see ``02_fork.py``)
- Use ``regenerate=True`` to drop the last assistant turn only (see ``01_regenerate.py``)
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

DB_FILE = f"tmp/team_time_travel_{int(time.time())}.db"


def get_population(city: str) -> str:
    data = {"Paris": "2.1M", "Tokyo": "13.9M"}
    return data.get(city, "unknown")


async def main() -> None:
    pop_agent = Agent(
        name="pop-agent",
        role="Answers population questions.",
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[get_population],
        db=SqliteDb(session_table="team_time_travel", db_file=DB_FILE),
    )
    team = Team(
        name="pop-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[pop_agent],
        db=SqliteDb(session_table="team_time_travel", db_file=DB_FILE),
        instructions="Delegate population questions and summarize the answer.",
    )

    original = await team.arun(
        input="What's the population of Paris?",
        session_id="team-sess-tt",
    )
    print(f"Original: {original.run_id}  msgs={len(original.messages or [])}")
    print(f"  content: {original.content}")
    print()

    # Continue from the end: this is the default. The source is preserved and
    # the follow-up becomes a new sibling because the original run completed.
    follow_up = await team.acontinue_run(
        run_id=original.run_id,
        session_id="team-sess-tt",
        continue_from="end",
        input="Now compare that with Tokyo.",
    )
    print(f"Follow-up: {follow_up.run_id}")
    print(f"  forked_from_run_id: {follow_up.forked_from_run_id}")
    print(f"  content: {follow_up.content}")
    print()

    # Resume from the last user message and re-ask a different city.
    # Completed runs auto-fork, so the Paris path is preserved.
    rewound = await team.acontinue_run(
        run_id=original.run_id,
        session_id="team-sess-tt",
        continue_from="last_user",
        input="Actually, tell me about Tokyo instead.",
    )
    print(f"Rewound: {rewound.run_id}")
    print(f"  forked_from_run_id: {rewound.forked_from_run_id}")
    print(f"  content: {rewound.content}")
    print()

    # Numeric form: pick an exact message index. Useful when the symbolic
    # boundaries don't land where you want — e.g. dropping more than just
    # the last assistant reply.
    print("Original team-run messages:")
    for i, m in enumerate(original.messages or [], start=1):
        preview = (m.content or "")[:60].replace("\n", " ")
        print(f"  [{i}] {m.role}: {preview}")
    print()

    rewound_to_index = await team.acontinue_run(
        run_id=original.run_id,
        session_id="team-sess-tt",
        continue_from=1,
        input="Tell me about Lagos instead.",
    )
    print(f"Rewound to index 1: {rewound_to_index.run_id}")
    print(f"  forked_from_message_index: {rewound_to_index.forked_from_message_index}")
    print(f"  content: {rewound_to_index.content}")
    print()

    # Inspect the session - all team runs coexist.
    session = team.db.get_session(session_id="team-sess-tt", session_type="team")
    team_runs = [r for r in (session.runs or []) if hasattr(r, "member_responses")]
    print(f"Session has {len(team_runs)} team row(s) (source preserved, forks added)")


if __name__ == "__main__":
    asyncio.run(main())
