"""
Cancel While Member Runs
========================
Cancel a team run while a member agent is actively streaming.

The cancellation propagates from the team to the in-flight member,
and both runs are persisted with status=cancelled.

Requires: PostgreSQL running on localhost:5532 (see cookbook/scripts/run_pgvector.sh)
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.run.team import ToolCallStartedEvent
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    id="researcher",
    role="Writes long-form research essays with many paragraphs",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=[
        "You are a researcher.",
        "Write very detailed, very long responses with many paragraphs.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="CancelWhileMemberRuns",
    mode=TeamMode.route,
    model=OpenAIResponses(id="gpt-5.4"),
    members=[researcher],
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    show_members_responses=True,
    store_tool_messages=True,
    store_history_messages=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_id = None
    cancelled = False
    delegation_started = False
    member_content_chunks = 0

    for event in team.run(
        input=(
            "Write a very long essay about the history of artificial intelligence"
            " with at least 10 major milestones. Be extremely detailed."
        ),
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id") and event.run_id:
            run_id = event.run_id

        # Watch for delegation kicking off so cancel lands while the member is in flight.
        if isinstance(event, ToolCallStartedEvent):
            tool_name = getattr(getattr(event, "tool", None), "tool_name", None)
            if tool_name == "delegate_task_to_member":
                delegation_started = True
                print(f"\n[delegation started: {tool_name}]")

        if hasattr(event, "content") and event.content:
            if delegation_started:
                member_content_chunks += 1
            print(event.content, end="", flush=True)

        if (
            delegation_started
            and member_content_chunks >= 10
            and not cancelled
            and run_id
        ):
            print(
                f"\n\nCancelling mid-member-stream after {member_content_chunks} member chunks"
            )
            team.cancel_run(run_id)
            cancelled = True

        if isinstance(event, TeamRunCancelledEvent):
            print("\nReceived TeamRunCancelled")
            break

    # Verify persistence — both the team run and the member run end up in
    # session.runs. Team runs carry team_id; member runs carry agent_id and
    # link back via parent_run_id.
    print("\n--- Verification ---")
    session = team.get_session(session_id=team.session_id)
    if session and session.runs:
        team_runs = [run for run in session.runs if getattr(run, "team_id", None)]
        member_runs = [run for run in session.runs if getattr(run, "agent_id", None)]

        for run in team_runs:
            print(
                f"Team run {run.run_id}: status={run.status}, "
                f"content_length={len(str(run.content or ''))}, "
                f"messages={len(run.messages or [])}"
            )

        for run in member_runs:
            print(
                f"Member run {run.run_id} (agent={run.agent_name}, parent={run.parent_run_id}): "
                f"status={run.status}, content_length={len(str(run.content or ''))}, "
                f"messages={len(run.messages or [])}"
            )
