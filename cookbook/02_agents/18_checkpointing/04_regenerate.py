"""Regenerate the last response via /continue with regenerate=True.

``regenerate=True`` is sugar over ``continue_from="last_user"``: it lands just
after the last user message, drops the previous assistant reply, and re-runs
the model loop.

**Always non-destructive.** Every regenerate creates a NEW run with a fresh
``run_id`` and fresh ``RunMetrics``; the source run stays intact. This
preserves the "1 run = 1 model loop" invariant - metrics, timestamps, and
audit trails always reflect exactly one model loop.

Two flavors:
- ``regenerate=True``                            -> fork. Both runs visible in
  session and history. Use when you want to compare attempts.
- ``regenerate=True, preserve_original=True``    -> fork, AND mark the source
  ``status=REGENERATED`` so history-builders skip it. The model sees only
  the new turn when re-rebuilding context for future runs.
- ``regenerate=True, additional_instructions=X`` -> append X as a user message
  before re-generating. Use this to steer the new output.

These compose. ``regenerate=True, preserve_original=True,
additional_instructions="be more concise"`` is the typical "let me try that
again with guidance, hide the old one from future context" pattern.

Compare to ``continue_from="last_user"`` (02_time_travel.py): same mechanism,
but ``regenerate`` picks the boundary for you.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses


async def main() -> None:
    agent = Agent(
        name="trivia-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(
            session_table="checkpoint_demo",
            db_file="tmp/checkpoint_regenerate.db",
        ),
        checkpoint="tool-batch",
        markdown=True,
    )

    # Original run
    original = await agent.arun(input="Give me 3 fun facts about octopuses.")
    print("--- Original ---")
    print(original.content)
    print()

    # Regenerate — creates a NEW run with a fresh run_id. The original is preserved.
    redo = await agent.acontinue_run(
        run_id=original.run_id,
        session_id=original.session_id,
        regenerate=True,
    )
    print("--- Regenerated (new run_id, original preserved) ---")
    print("  run_id:", redo.run_id, "(new)")
    print(
        "  forked_from_run_id:",
        redo.forked_from_run_id,
        "(original:",
        original.run_id,
        ")",
    )
    print(redo.content)
    print()

    # Regenerate with steering — append instructions before re-running.
    steered = await agent.acontinue_run(
        run_id=original.run_id,
        session_id=original.session_id,
        regenerate=True,
        additional_instructions="Make them weirder, and add a citation for each.",
    )
    print("--- Regenerated with steering ---")
    print(steered.content)
    print()

    # Regenerate but keep the old one — preserve_original creates a fork.
    preserved = await agent.acontinue_run(
        run_id=original.run_id,
        session_id=original.session_id,
        regenerate=True,
        preserve_original=True,
        additional_instructions="Now do it in haiku form.",
    )
    print("--- Regenerated with preserve_original=True (fork) ---")
    print("  run_id:", preserved.run_id, "(new)")
    print("  regenerated_from:", preserved.regenerated_from)
    print(preserved.content)
    print()

    # Verify the session: 4 runs now — original + 2 regenerates + 1 preserved-style.
    # Each has its own metrics; the source is untouched.
    session = agent.db.get_session(session_id=original.session_id, session_type="agent")
    print(f"Session has {len(session.runs or [])} runs:")
    for r in session.runs or []:
        line = f"  - {r.run_id} [{r.status}]"
        if r.regenerated_from:
            line += f" regenerated_from={r.regenerated_from}"
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
