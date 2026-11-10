"""Regenerate the last response via /continue with regenerate=True.

``regenerate=True`` drops the trailing assistant response and re-runs the
model loop. Intermediate tool exchanges (assistant tool_calls + their
tool-role results) are **preserved** — the model regenerates a fresh
summary of the same tool outputs without re-invoking the tools.

**Always non-destructive.** Every regenerate creates a NEW run with a fresh
``run_id`` and fresh ``RunMetrics``; the source run is always retained in
storage. This preserves the "1 run = 1 model loop" invariant - metrics,
timestamps, and audit trails always reflect exactly one model loop.

``replace_original`` controls only whether the source run stays *visible* in
history (the source row is always kept either way):
- ``regenerate=True`` (default)                  -> the source is marked
  ``status=REGENERATED`` and hidden from history; the new run replaces it.
  Future runs see only the new turn when context is rebuilt.
- ``regenerate=True, replace_original=False``     -> both runs stay visible in
  session and history. Use when you want to compare attempts side by side.
- ``regenerate=True, additional_instructions=X``  -> append X as a user message
  before re-generating. Use this to steer the new output.

``replace_original`` only decides whether THIS regenerate hides the run it is
regenerating from. It does NOT un-hide a run an earlier regenerate already
replaced — so ``replace_original=False`` is only meaningful when the source run
is still COMPLETED. Regenerate the *latest* run, not an already-replaced one.

These compose. ``regenerate=True, additional_instructions="be more concise"``
is the typical "let me try that again with guidance, replace the old one"
pattern.

Compare to ``continue_from="last_user"`` (../20_time_travel/01_continue_from.py): both rewind, but
``"last_user"`` drops the whole post-user tail including tool exchanges,
forcing tools to be re-invoked. ``regenerate=True`` keeps the tool exchange
so only the final summary is regenerated.
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


async def main() -> None:
    agent = Agent(
        name="trivia-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=PostgresDb(
            db_url=db_url,
            session_table="checkpoint_demo",
        ),
        checkpoint="tool-batch",
        markdown=True,
    )

    # Keep both demos in one session so the final listing tells the whole story.
    session_id = "checkpoint-regenerate-demo"

    # ------------------------------------------------------------------
    # Demo 1: regenerate REPLACES the original (default replace_original=True).
    # Each regenerate targets the *latest* run, so the chain reads
    # q1 -> r1 -> r1b, with every superseded run marked REGENERATED.
    # ------------------------------------------------------------------
    q1 = await agent.arun(
        input="Give me 3 fun rare facts about the world.", session_id=session_id
    )
    print("--- Demo 1: original ---")
    print(q1.content)
    print()

    r1 = await agent.acontinue_run(
        run_id=q1.run_id, session_id=session_id, regenerate=True
    )
    print("--- Regenerated (default: q1 hidden, r1 replaces it) ---")
    print("  run_id:", r1.run_id, "(new)")
    print("  forked_from_run_id:", r1.forked_from_run_id, "(was", q1.run_id, ")")
    print(r1.content)
    print()

    # Steering composes — regenerate the LATEST run (r1), not the already-hidden q1.
    r1b = await agent.acontinue_run(
        run_id=r1.run_id,
        session_id=session_id,
        regenerate=True,
        additional_instructions="Make them weirder, and add a citation for each.",
    )
    print("--- Regenerated again with steering (r1 hidden, r1b replaces it) ---")
    print(r1b.content)
    print()

    # ------------------------------------------------------------------
    # Demo 2: KEEP BOTH visible (replace_original=False). The source must be a
    # COMPLETED run for this to mean anything — replace_original=False only
    # decides whether THIS regenerate hides its source; it never un-hides a run
    # an earlier regenerate already replaced. So start from a fresh run.
    # ------------------------------------------------------------------
    q2 = await agent.arun(
        input="Give me 3 fun rare facts about the ocean.", session_id=session_id
    )
    print("--- Demo 2: original ---")
    print(q2.content)
    print()

    r2 = await agent.acontinue_run(
        run_id=q2.run_id,
        session_id=session_id,
        regenerate=True,
        replace_original=False,
        additional_instructions="Now do it in haiku form.",
    )
    print("--- Regenerated with replace_original=False (q2 stays visible) ---")
    print("  run_id:", r2.run_id, "(new)")
    print("  regenerated_from:", r2.regenerated_from)
    print(r2.content)
    print()

    # Verify the session. Expected:
    #   q1  [REGENERATED]  (replaced by r1)
    #   r1  [REGENERATED]  (replaced by r1b)
    #   r1b [COMPLETED]    (current answer for demo 1)
    #   q2  [COMPLETED]    (kept visible — replace_original=False)
    #   r2  [COMPLETED]    (sits alongside q2)
    session = agent.db.get_session(session_id=session_id, session_type="agent")
    print(f"Session has {len(session.runs or [])} runs:")
    for r in session.runs or []:
        line = f"  - {r.run_id} [{r.status}]"
        if r.regenerated_from:
            line += f" regenerated_from={r.regenerated_from}"
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
