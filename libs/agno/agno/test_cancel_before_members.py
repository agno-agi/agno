"""
Edge case 1: Cancel BEFORE any member delegation happens.

The team leader's model call hasn't even returned a tool call yet.
We cancel immediately after getting the run_id.

Expected: Session should contain one run with status=cancelled.
Current bug hypothesis: Session may have no runs at all.
"""

import threading
import time

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunEvent
from agno.team import Team

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a researcher. Write detailed responses.",
)

team = Team(
    name="CancelBeforeMembers",
    members=[researcher],
    model=OpenAIChat(id="gpt-4o-mini"),
    db=PostgresDb(db_url=DB_URL),
    store_tool_messages=True,
    store_history_messages=True,
)

run_id = None
cancelled = False
event_count = 0

print("--- Edge Case 1: Cancel BEFORE member delegation ---")
print("Cancelling as soon as we get the run_id (before any delegation)\n")

for event in team.run(
    input="Tell me about quantum computing",
    stream=True,
    stream_events=True,
):
    event_count += 1

    # Capture run_id from the very first event
    if run_id is None and hasattr(event, "run_id") and event.run_id:
        run_id = event.run_id
        # Cancel IMMEDIATELY - before any member delegation can happen
        print(f"Got run_id: {run_id}")
        print("Cancelling immediately...")
        team.cancel_run(run_id)
        cancelled = True

    if hasattr(event, "event") and event.event == TeamRunEvent.run_cancelled:
        print("Received run_cancelled event")
        break

print(f"\nTotal events received: {event_count}")

# Verify persistence
print("\n--- Verification ---")
session = team.get_session(session_id=team.session_id)
if session:
    print(f"Session ID: {session.session_id}")
    print(f"Number of runs in session: {len(session.runs or [])}")
    if session.runs:
        for i, run in enumerate(session.runs):
            print(f"  Run {i}: status={run.status}, run_id={run.run_id}")
            print(f"    Content: {bool(run.content)} (length={len(run.content or '')})")
            print(f"    Messages: {len(run.messages or [])}")
            if hasattr(run, "member_responses"):
                print(f"    Member responses: {len(run.member_responses)}")
    else:
        print("  BUG: No runs found in session! Should have 1 cancelled run.")
else:
    print("BUG: No session found at all!")
