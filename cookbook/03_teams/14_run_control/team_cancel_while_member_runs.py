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
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunEvent
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a researcher. Write very detailed, very long responses with many paragraphs.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="CancelWhileMemberRuns",
    members=[researcher],
    model=OpenAIChat(id="gpt-4o-mini"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    store_tool_messages=True,
    store_history_messages=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_id = None
    cancelled = False
    content_chunks: list = []

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

        if hasattr(event, "content") and event.content:
            content_chunks.append(event.content)
            print(event.content, end="", flush=True)

        # Cancel after seeing substantial member content (member is in flight)
        if len(content_chunks) >= 30 and run_id and not cancelled:
            print(f"\n\nCancelling after {len(content_chunks)} content chunks")
            team.cancel_run(run_id)
            cancelled = True

        if hasattr(event, "event") and event.event == TeamRunEvent.run_cancelled:
            print("\nReceived run_cancelled event")
            break

    # Verify persistence
    print("\n--- Verification ---")
    session = team.get_session(session_id=team.session_id)
    if session and session.runs:
        for i, run in enumerate(session.runs):
            print(
                f"Run {i}: status={run.status}, content_length={len(str(run.content or ''))}"
            )
            print(f"  Messages: {len(run.messages or [])}")
