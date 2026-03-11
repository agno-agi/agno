"""
Edge case: Cancel WHILE a member agent is actively running/streaming.

We wait until we see member events flowing, then cancel the team run.

Expected:
- The member's run should also get cancelled (not keep running).
- The team session should contain one cancelled team run.
- The member's partial work should be visible somehow.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunEvent
from agno.team import Team

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a researcher. Write very detailed, very long responses with many paragraphs.",
)

team = Team(
    name="CancelWhileMemberRuns",
    members=[researcher],
    model=OpenAIChat(id="gpt-4o-mini"),
    db=PostgresDb(db_url=DB_URL),
    store_tool_messages=True,
    store_history_messages=True,
    # store_member_responses=True,
)

run_id = None
cancelled = False
content_chunks: list = []
member_events_seen = 0

print("--- Edge Case 2: Cancel WHILE member is running ---")
print("Waiting for member content to flow, then cancelling\n")

for event in team.run(
    input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones. Be extremely detailed.",
    stream=True,
    stream_events=True,
):
    if run_id is None and hasattr(event, "run_id") and event.run_id:
        run_id = event.run_id

    if hasattr(event, "content") and event.content:
        content_chunks.append(event.content)
        print(event.content, end="", flush=True)
        member_events_seen += 1

    # Cancel after seeing substantial member content (member is definitely in flight)
    if member_events_seen >= 30 and run_id and not cancelled:
        print(f"\n\n--- Cancelling after {member_events_seen} content chunks ---")
        team.cancel_run(run_id)
        cancelled = True

    if hasattr(event, "event") and event.event == TeamRunEvent.run_cancelled:
        print("\nReceived run_cancelled event")
        break

print(f"\nTotal content chunks before cancel: {len(content_chunks)}")

# Verify persistence
print("\n--- Verification ---")
session = team.get_session(session_id=team.session_id)
if session:
    print(f"Session ID: {session.session_id}")
    print(f"Number of runs in session: {len(session.runs or [])}")
    if session.runs:
        for i, run in enumerate(session.runs):
            run_type = "TeamRunOutput" if hasattr(run, "team_id") else "RunOutput"
            print(f"  Run {i} ({run_type}): status={run.status}, run_id={run.run_id}")
            print(f"    Content: {bool(run.content)} (length={len(str(run.content or ''))})")
            print(f"    Messages: {len(run.messages or [])}")
            if hasattr(run, "member_responses"):
                print(f"    Member responses: {len(run.member_responses)}")
                for j, mr in enumerate(run.member_responses):
                    mr_type = "TeamRunOutput" if hasattr(mr, "team_id") else "RunOutput"
                    print(f"      Member {j} ({mr_type}): status={mr.status}")
                    print(f"        Content: {bool(mr.content)} (length={len(str(mr.content or ''))})")
                    print(f"        Messages: {len(mr.messages or [])}")
    else:
        print("  BUG: No runs found in session!")
else:
    print("BUG: No session found!")