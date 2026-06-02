"""Time-travel a team run via `from_checkpoint=K` (destructive).

``from_checkpoint=K`` without ``fork=True`` truncates the team's messages
**in place** — same ``run_id`` as the source. Use when you want to rewind
a specific run rather than create a sibling.

For non-destructive variants:
- Pair with ``fork=True`` to create a sibling (see ``02_fork.py``)
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

    # Truncate in place to message index 2 (system + user) and re-ask a
    # different city. Same run_id — destructive rewind.
    rewound = await team.acontinue_run(
        run_id=original.run_id,
        session_id="team-sess-tt",
        from_checkpoint=2,
        input="Actually, tell me about Tokyo instead.",
    )
    print(f"Rewound: {rewound.run_id}")
    print(f"  same run_id as original: {rewound.run_id == original.run_id}")
    print(f"  content: {rewound.content}")
    print()

    # Inspect the session — only ONE team row exists (the same one, rewritten)
    session = team.db.get_session(session_id="team-sess-tt", session_type="team")
    team_runs = [r for r in (session.runs or []) if hasattr(r, "member_responses")]
    print(
        f"Session has {len(team_runs)} team row(s) (destructive rewind reused the row)"
    )


if __name__ == "__main__":
    asyncio.run(main())
