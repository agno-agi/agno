"""Tool / model error persistence for a Team — does the conversation survive?

Team parity with ../../02_agents/18_checkpointing/02_tool_error_persistence.py.

Two scenarios that look similar but resolve differently:

SCENARIO A — A tool raises a regular Python exception.
  The team's model loop catches it, turns it into a tool-role message with
  ``tool_call_error=True``, fires the checkpoint hook, and carries on. The run
  completes with the error visible in messages. No data loss.

SCENARIO B — The team's model call itself fails before any tool batch.
  (Simulated with an invalid API key.) The exception escapes the model loop and
  the per-batch checkpoint hook never ran. ``flush_in_flight_messages_on_error_team``
  flushes the in-flight ``run_messages`` onto the ERROR row before persisting, so
  the conversation that led to the failure is preserved.

SCENARIO C — /continue the failed (ERROR) team run.
  ERROR is not COMPLETED, so /continue resumes in place (same run_id). With the
  messages preserved, the model has the conversation to retry against.
"""

import asyncio
import os
import time

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

DB_FILE = f"tmp/team_tool_error_persist_{int(time.time())}.db"


def broken_tool(query: str) -> str:
    """A normal tool that always raises. The model loop catches this internally —
    it becomes a tool-role message with tool_call_error=True, and the run continues."""
    raise ValueError(f"this tool always fails on query={query}")


async def scenario_a_tool_error() -> None:
    """Team-level tool raises ValueError -> handled gracefully by the model loop."""
    print("=" * 70)
    print("SCENARIO A: Tool raises ValueError (caught by the team model loop)")
    print("=" * 70)

    team = Team(
        name="a-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[],
        tools=[broken_tool],
        db=SqliteDb(session_table="team_tool_err_a", db_file=DB_FILE),
        checkpoint="tool-batch",
        instructions="Call broken_tool once with the user's query, then summarize.",
    )

    try:
        response = await team.arun(input="hello", session_id="sess-A")
        print(f"team.arun returned. status={response.status}")
        print(f"  run_id:  {response.run_id}")
        print(f"  msgs:    {len(response.messages or [])}")
    except Exception as e:
        print(f"team.arun RAISED unexpectedly: {type(e).__name__}: {e}")

    fresh = Team(
        name="a-team-reader",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[],
        db=SqliteDb(session_table="team_tool_err_a", db_file=DB_FILE),
    )
    session = fresh.db.get_session(session_id="sess-A", session_type="team")
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
    """The team's model call fails before any tool batch. With the team flush
    helper, the in-flight conversation is preserved on the ERROR row.

    Returns the failed run_id so Scenario C can /continue it.
    """
    print("=" * 70)
    print("SCENARIO B: Team model call fails (invalid key) — escapes the loop")
    print("=" * 70)

    real_key = os.environ.get("OPENAI_API_KEY", "")
    os.environ["OPENAI_API_KEY"] = (
        "sk-invalid-key-deliberately-broken-to-force-auth-error"
    )

    try:
        team = Team(
            name="b-team",
            model=OpenAIResponses(id="gpt-5.4"),
            members=[],
            db=SqliteDb(session_table="team_tool_err_b", db_file=DB_FILE),
            checkpoint="tool-batch",
            instructions="You are a helpful assistant. Answer concisely.",
        )

        failed_run_id = ""
        try:
            response = await team.arun(input="say hi", session_id="sess-B")
            print(f"team.arun returned. status={response.status}")
            failed_run_id = response.run_id or ""
        except Exception as e:
            print(f"team.arun RAISED: {type(e).__name__}: {str(e)[:120]}")

        print("\n--- DB state after failed model call ---")
        os.environ["OPENAI_API_KEY"] = real_key or "sk-not-used"
        fresh = Team(
            name="b-team-reader",
            model=OpenAIResponses(id="gpt-5.4"),
            members=[],
            db=SqliteDb(session_table="team_tool_err_b", db_file=DB_FILE),
        )
        session = fresh.db.get_session(session_id="sess-B", session_type="team")
        if not session or not session.runs:
            print("DB has no runs persisted.")
            return ""
        for r in session.runs:
            msg_count = len(r.messages or [])
            print(f"\nDB run: status={r.status}, msgs={msg_count}")
            if msg_count == 0:
                print("  [empty] messages list is EMPTY — the conversation that led")
                print("          to the failure was lost (flush helper NOT applied).")
            else:
                print("  [ok] messages preserved by the team flush helper.")
                for i, m in enumerate(r.messages or []):
                    preview = (m.content or "")[:80] if m.content else ""
                    print(f"  [{i}] {m.role}: {preview}")
            if not failed_run_id:
                failed_run_id = r.run_id or ""
        return failed_run_id
    finally:
        if real_key:
            os.environ["OPENAI_API_KEY"] = real_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)


async def scenario_c_continue_failed_run(failed_run_id: str) -> None:
    """/continue the failed (ERROR) team run. ERROR is not COMPLETED, so it
    resumes in place — same run_id. With messages preserved, the model can retry."""
    print("=" * 70)
    print("SCENARIO C: /continue on the failed team run — retry with same run_id")
    print("=" * 70)

    if not failed_run_id:
        print("No failed run_id from scenario B — skipping.")
        return

    team = Team(
        name="b-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[],
        db=SqliteDb(session_table="team_tool_err_b", db_file=DB_FILE),
        checkpoint="tool-batch",
        instructions="You are a helpful assistant. Answer concisely.",
    )

    try:
        resumed = await team.acontinue_run(run_id=failed_run_id, session_id="sess-B")
        print(f"acontinue_run returned. status={resumed.status}")
        print(f"  run_id:  {resumed.run_id}")
        print(f"  same as failed run? {resumed.run_id == failed_run_id}")
        print(f"  msgs:    {len(resumed.messages or [])}")
    except Exception as e:
        print(f"acontinue_run RAISED: {type(e).__name__}: {str(e)[:200]}")
        return

    print("\n--- DB state after /continue ---")
    session = team.db.get_session(session_id="sess-B", session_type="team")
    if session and session.runs:
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
