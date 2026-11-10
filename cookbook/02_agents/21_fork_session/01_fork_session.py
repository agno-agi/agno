"""Fork a session via agent.fork_session().

``fork_session`` deep-copies every run from the source session into a brand-
new session with a fresh ``session_id`` and fresh ``run_id``s. The source is
untouched. Useful for spinning up an independent conversation that starts from
a known-good state.

Distinction from ``fork`` (../20_time_travel/02_fork_run.py):
- ``fork``           → new run inside the **same** session (run-level)
- ``fork_session`` → new session containing copies of every run (session-level)

Lineage:
- ``run.forked_from_session_id``                       → the run's *original*
  session_id, preserved across nested forks
- ``session.session_data["forked_from_session_id"]``   → the *immediate* parent
  session_id (overwritten on each re-fork)

So for root → mid → leaf:
- ``leaf.session.session_data["forked_from_session_id"] == mid``
- ``leaf.runs[*].forked_from_session_id == root``

The source session is read scoped to the caller's ``user_id`` — you can only
fork your own sessions.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses


async def main() -> None:
    agent = Agent(
        name="planner",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(
            session_table="checkpoint_demo",
            db_file="tmp/checkpoint_fork_session.db",
        ),
        checkpoint="tool-batch",
        markdown=True,
    )

    original_sid = "trip-planning-original"
    user_id = "demo-user"

    # Build a conversation in the original session.
    await agent.arun(
        input="I'm planning a trip to Japan. What are the top 3 cities to visit?",
        session_id=original_sid,
        user_id=user_id,
    )
    await agent.arun(
        input="Tell me more about Kyoto.",
        session_id=original_sid,
        user_id=user_id,
    )

    # Branch the session. The original is untouched; we get a fresh session_id
    # containing copies of every run.
    new_sid = await agent.afork_session(
        source_session_id=original_sid,
        user_id=user_id,
    )
    print(f"Branched: {original_sid} → {new_sid}")
    print()

    # Continue the forked session in a different direction.
    forked_run = await agent.arun(
        input="Actually, what about Osaka's street food scene?",
        session_id=new_sid,
        user_id=user_id,
    )
    print("--- Branched session continued ---")
    print(forked_run.content[:200], "...")
    print()

    # The original session is unchanged — you can continue it independently.
    original_run = await agent.arun(
        input="Which Kyoto temples are must-see?",
        session_id=original_sid,
        user_id=user_id,
    )
    print("--- Original session continued ---")
    print(original_run.content[:200], "...")
    print()

    # Inspect both sessions.
    for sid, label in [(original_sid, "original"), (new_sid, "forked")]:
        s = agent.db.get_session(session_id=sid, session_type="agent")
        forked_from_session_id = (s.session_data or {}).get("forked_from_session_id")
        print(
            f"{label}: {sid}  ({len(s.runs or [])} runs)"
            + (
                f"  forked_from_session_id={forked_from_session_id}"
                if forked_from_session_id
                else ""
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
