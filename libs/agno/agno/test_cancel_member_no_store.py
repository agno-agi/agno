"""
Edge case 3: Cancel while member is in flight, WITHOUT store_member_responses=True.

This is the hardest case: the team doesn't store member responses by default,
but when cancelled mid-delegation, we still want to know that a member was
running and capture its partial state.

Expected:
- Team session should have 1 cancelled run with content.
- Even without store_member_responses, the cancelled run should have
  some record of the member work (at minimum in team content, ideally
  member_responses preserved for cancelled runs).

Current bug hypothesis: member_responses is [] and partial member content is lost.
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
    instructions="You are a researcher. Write very detailed, very long responses.",
)

team = Team(
    name="CancelMemberNoStore",
    members=[researcher],
    model=OpenAIChat(id="gpt-4o-mini"),
    db=PostgresDb(db_url=DB_URL),
    store_tool_messages=True,
    store_history_messages=True,
    # NOTE: store_member_responses is False (default)
)

run_id = None
cancelled = False
content_chunks: list = []
member_events_seen = 0

print("--- Edge Case 3: Cancel while member runs, store_member_responses=False ---")
print("This tests whether partial member work is preserved without store_member_responses\n")

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

    # Cancel after seeing member content
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
            print(f"    Content present: {bool(run.content)}")
            if run.content:
                content_str = str(run.content)
                print(f"    Content length: {len(content_str)}")
                print(f"    Content preview: {content_str[:200]}...")
            print(f"    Messages: {len(run.messages or [])}")
            if hasattr(run, "member_responses"):
                print(f"    Member responses count: {len(run.member_responses)}")
                if run.member_responses:
                    for j, mr in enumerate(run.member_responses):
                        print(f"      Member {j}: status={mr.status}, content_len={len(str(mr.content or ''))}")
                else:
                    print("    (member_responses is empty - expected with store_member_responses=False)")
                    print("    Q: Is the partial member content at least captured in the team run content?")
    else:
        print("  BUG: No runs found in session!")
else:
    print("BUG: No session found!")
