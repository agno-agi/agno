"""Tool / model error persistence — does the conversation survive a failure?

This cookbook reproduces two scenarios that look similar but resolve very
differently:

SCENARIO A — Tool raises a regular Python exception.
  The model loop catches the tool error internally, turns it into a
  tool-role message with ``tool_call_error=True``, fires the checkpoint
  hook, and the model carries on. The run completes normally with the
  error visible in messages. **No data loss.**

SCENARIO B — The model call itself fails before any tool batch fires.
  (Simulated here with an invalid API key — provider auth error.) The
  exception escapes the model loop, the per-batch checkpoint hook never
  ran, and update_run_response never populated run_response.messages.
  Without the fix, the terminal ERROR write persists an empty-message row
  and the user/system message that led to the failure is lost.

  With ``flush_in_flight_messages_on_error`` (in ``agent/_run.py``), the
  agent's outer ``except`` block flushes the in-flight ``run_messages``
  into ``run_response.messages`` before persisting. The conversation that
  led to the failure is preserved.

To verify the fix, run this cookbook twice:
  1. As-is — observe scenario B preserves messages.
  2. After ``git stash`` of the flush helper change — observe scenario B
     persists an empty messages list.
"""

import asyncio
import os
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

DB_FILE = f"tmp/tool_error_persist_{int(time.time())}.db"


def broken_tool(query: str) -> str:
    """A normal tool that always raises ValueError. The model loop catches
    this internally — it becomes a tool-role message with tool_call_error=True,
    and the model continues."""
    raise ValueError(f"this tool always fails on query={query}")


async def scenario_a_tool_error() -> None:
    """Tool raises ValueError → handled gracefully by the model loop."""
    print("=" * 70)
    print("SCENARIO A: Tool raises ValueError (caught by model loop)")
    print("=" * 70)

    agent = Agent(
        name="a-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(session_table="tool_err_demo_a", db_file=DB_FILE),
        checkpoint="steps",
        tools=[broken_tool],
        retries=0,
        instructions="Call broken_tool once with the user's query, then summarize.",
    )

    try:
        response = await agent.arun(input="hello", session_id="sess-A")
        print(f"agent.arun returned. status={response.status}")
        print(f"  run_id:  {response.run_id}")
        print(f"  tools:   {len(response.tools or [])}")
        print(f"  msgs:    {len(response.messages or [])}")
        print(f"  content (truncated): {(response.content or '')[:120]}")
    except Exception as e:
        print(f"agent.arun RAISED unexpectedly: {type(e).__name__}: {e}")

    # Inspect DB
    fresh = Agent(
        name="a-agent-reader",
        db=SqliteDb(session_table="tool_err_demo_a", db_file=DB_FILE),
        model=OpenAIResponses(id="gpt-5.4"),
    )
    session = fresh.db.get_session(session_id="sess-A", session_type="agent")
    if session and session.runs:
        for r in session.runs:
            print(
                f"\nDB run: status={r.status}, msgs={len(r.messages or [])}, tools={len(r.tools or [])}"
            )
            for i, m in enumerate(r.messages or []):
                err = (
                    " [tool_call_error]" if getattr(m, "tool_call_error", False) else ""
                )
                preview = (m.content or "")[:80] if m.content else ""
                print(f"  [{i}] {m.role}: {preview}{err}")
    print()


async def scenario_b_model_call_fails() -> str:
    """Model API call itself fails before any tool batch — the failure
    escapes the model loop. With the flush helper, the in-flight
    conversation is preserved in run_response.messages. Without it,
    the ERROR row has no messages.

    Returns the failed run_id so Scenario C can /continue it.
    """
    print("=" * 70)
    print("SCENARIO B: Model API call fails (invalid key) — escapes the loop")
    print("=" * 70)

    # Save the real key and substitute a bad one so the model call deterministically fails.
    real_key = os.environ.get("OPENAI_API_KEY", "")
    os.environ["OPENAI_API_KEY"] = (
        "sk-invalid-key-deliberately-broken-to-force-auth-error"
    )

    try:
        agent = Agent(
            name="b-agent",
            model=OpenAIResponses(id="gpt-5.4"),
            db=SqliteDb(session_table="tool_err_demo_b", db_file=DB_FILE),
            checkpoint="steps",
            retries=0,
            instructions="You are a helpful assistant. Answer concisely.",
        )

        failed_run_id = ""
        try:
            response = await agent.arun(input="say hi", session_id="sess-B")
            print(f"agent.arun returned. status={response.status}")
            print(f"  run_id:  {response.run_id}")
            print(f"  msgs:    {len(response.messages or [])}")
            print(f"  content (truncated): {(response.content or '')[:120]}")
            failed_run_id = response.run_id or ""
        except Exception as e:
            print(f"agent.arun RAISED: {type(e).__name__}: {str(e)[:120]}")

        # Inspect DB — this is the key observation
        print("\n--- DB state after failed model call ---")
        # Restore the key so the reader agent can construct its model (it doesn't actually call).
        os.environ["OPENAI_API_KEY"] = real_key or "sk-not-used"
        fresh = Agent(
            name="b-agent-reader",
            db=SqliteDb(session_table="tool_err_demo_b", db_file=DB_FILE),
            model=OpenAIResponses(id="gpt-5.4"),
        )
        session = fresh.db.get_session(session_id="sess-B", session_type="agent")
        if not session or not session.runs:
            print("DB has no runs persisted.")
            return ""
        for r in session.runs:
            msg_count = len(r.messages or [])
            print(f"\nDB run: status={r.status}, msgs={msg_count}")
            if msg_count == 0:
                print("  ⚠ messages list is EMPTY — conversation that led to the")
                print("    failure was lost. This is what Yash's review flagged.")
                print("    If you see this, the flush helper was NOT applied.")
            else:
                print("  ✓ messages preserved by the flush helper.")
                for i, m in enumerate(r.messages or []):
                    preview = (m.content or "")[:80] if m.content else ""
                    print(f"  [{i}] {m.role}: {preview}")
            if not failed_run_id:
                failed_run_id = r.run_id or ""
        return failed_run_id
    finally:
        # Always restore the real key
        if real_key:
            os.environ["OPENAI_API_KEY"] = real_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)


async def scenario_c_continue_failed_run(failed_run_id: str) -> None:
    """Call /continue on the failed run. The auto-fork-on-COMPLETED rule does
    NOT trigger here (status is ERROR, not COMPLETED) — so /continue resumes
    the failed run *in place*, same ``run_id``. With the messages preserved
    by the flush helper, the model has [system, user] to work with and can
    actually answer this time (real API key restored).

    This is the "retry an ERROR run" path:
    - The persisted system + user message survive the failure.
    - /continue picks them up, calls the model with valid credentials.
    - The model responds, run becomes COMPLETED.
    - run_id is unchanged — same logical conversation turn.
    """
    print("=" * 70)
    print("SCENARIO C: /continue on the failed run — retry with same run_id")
    print("=" * 70)

    if not failed_run_id:
        print("No failed run_id from scenario B — skipping.")
        return

    # Real API key is restored (scenario_b's finally block).
    agent = Agent(
        name="b-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(session_table="tool_err_demo_b", db_file=DB_FILE),
        checkpoint="steps",
        instructions="You are a helpful assistant. Answer concisely.",
    )

    try:
        resumed = await agent.acontinue_run(
            run_id=failed_run_id,
            session_id="sess-B",
        )
        print(f"acontinue_run returned. status={resumed.status}")
        print(f"  run_id:  {resumed.run_id}")
        print(f"  same as failed run? {resumed.run_id == failed_run_id}")
        print(f"  msgs:    {len(resumed.messages or [])}")
        print(f"  content (truncated): {(resumed.content or '')[:200]}")
    except Exception as e:
        print(f"acontinue_run RAISED: {type(e).__name__}: {str(e)[:200]}")
        return

    # Inspect the DB — there should be ONE run, same id, now COMPLETED.
    print("\n--- DB state after /continue ---")
    session = agent.db.get_session(session_id="sess-B", session_type="agent")
    if not session or not session.runs:
        print("No runs.")
        return
    print(f"Session has {len(session.runs or [])} run(s):")
    for r in session.runs:
        print(f"  - {r.run_id} [{r.status}]  msgs={len(r.messages or [])}")


async def main() -> None:
    await scenario_a_tool_error()
    print()
    failed_run_id = await scenario_b_model_call_fails()
    print()
    await scenario_c_continue_failed_run(failed_run_id or "")


if __name__ == "__main__":
    asyncio.run(main())
