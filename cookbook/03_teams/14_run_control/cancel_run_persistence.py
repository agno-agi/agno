"""
Demonstrates cancelling a Team run mid-stream and verifying
that partial content and messages are preserved in the database.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunEvent
from agno.team import Team

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a researcher. Write detailed responses.",
)

team = Team(
    name="Test Team",
    members=[researcher],
    model=OpenAIChat(id="gpt-4o-mini"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    store_tool_messages=True,
    store_history_messages=True,
)

run_id = None
cancelled = False
content_chunks: list = []

for event in team.run(
    input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
    stream=True,
    stream_events=True,
):
    if run_id is None and hasattr(event, "run_id") and event.run_id:
        run_id = event.run_id

    if hasattr(event, "content") and event.content:
        content_chunks.append(event.content)
        print(event.content, end="", flush=True)

    # Cancel after collecting some content
    if len(content_chunks) >= 20 and run_id and not cancelled:
        team.cancel_run(run_id)
        cancelled = True

    if hasattr(event, "event") and event.event == TeamRunEvent.run_cancelled:
        print("\nRun was cancelled!")
        break

# Verify persistence
session = team.get_session(session_id=team.session_id)
if session and session.runs:
    last_run = session.runs[-1]
    print(f"\nStatus: {last_run.status}")
    print(
        f"Content preserved: {bool(last_run.content)} (length: {len(last_run.content or '')})"
    )
    print(f"Messages preserved: {len(last_run.messages or [])} messages")
else:
    print("No session or runs found!")
