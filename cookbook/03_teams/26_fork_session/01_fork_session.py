"""Fork a team session via `team.fork_session()`.

Session-level forking (fork_session) is distinct from run-level forking (fork=True):
- ``regenerate`` / ``fork`` → new team **run** in the same session
- ``fork_session`` → new **session** containing copies of every run

Use ``fork_session`` when you want a completely independent conversation
thread that starts from the current state. The new session is durable,
queryable, and unrelated to the source — they can diverge freely.

Lineage:
- ``session.session_data["forked_from_session_id"]``: immediate parent session_id
  (overwritten on each re-fork)
- ``run.forked_from_session_id``: each run's **original** session_id, preserved
  across nested forks

So for root → mid → leaf forks:
- ``leaf.session.forked_from_session_id == mid`` (immediate)
- ``leaf.runs[*].forked_from_session_id == root`` (original)
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

DB_FILE = f"tmp/team_fork_session_{int(time.time())}.db"


def get_weather(city: str) -> str:
    data = {"Paris": "Cloudy, 14°C", "Tokyo": "Sunny, 22°C"}
    return data.get(city, "unknown")


async def main() -> None:
    weather_agent = Agent(
        name="weather-agent",
        role="Answers weather questions.",
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[get_weather],
        db=SqliteDb(session_table="team_fork", db_file=DB_FILE),
    )
    team = Team(
        name="travel-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[weather_agent],
        db=SqliteDb(session_table="team_fork", db_file=DB_FILE),
        instructions="Delegate to weather-agent and summarize.",
    )

    # Step 1: build a conversation in the original session.
    print("=" * 70)
    print("STEP 1: Build a conversation in the original session")
    print("=" * 70)
    original_sid = "team-fork-original"
    await team.arun(input="What's the weather in Paris?", session_id=original_sid)
    await team.arun(input="What about Tokyo?", session_id=original_sid)

    # Step 2: fork the session.
    print("\n" + "=" * 70)
    print("STEP 2: Branch the session")
    print("=" * 70)
    new_sid = await team.afork_session(source_session_id=original_sid)
    print(f"  Original session: {original_sid}")
    print(f"  Branched session: {new_sid}")

    # Step 3: continue the forked session independently.
    print("\n" + "=" * 70)
    print("STEP 3: Continue the forked session (independent)")
    print("=" * 70)
    forked_run = await team.arun(
        input="Now compare them and recommend one for a winter trip.",
        session_id=new_sid,
    )
    print(f"  forked_run: {forked_run.content}")

    # Step 4: original session is untouched.
    print("\n" + "=" * 70)
    print("STEP 4: Original session is unaffected")
    print("=" * 70)
    original_session = team.db.get_session(session_id=original_sid, session_type="team")
    forked_session = team.db.get_session(session_id=new_sid, session_type="team")

    print(f"  Original session: {len(original_session.runs or [])} runs")
    print(
        f"  Branched session: {len(forked_session.runs or [])} runs (2 inherited + 1 new)"
    )

    # Lineage check
    if (
        forked_session.session_data
        and "forked_from_session_id" in forked_session.session_data
    ):
        print(
            f"  forked session's forked_from_session_id: {forked_session.session_data['forked_from_session_id']}"
        )
    for r in forked_session.runs or []:
        bf = getattr(r, "forked_from_session_id", None)
        if bf:
            print(f"  run {r.run_id[:8]}… forked_from_session_id={bf}")


if __name__ == "__main__":
    asyncio.run(main())
