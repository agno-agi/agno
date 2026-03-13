"""
Cancel Run Persistence
======================
Cancel an agent run mid-stream and verify that partial content
and messages are preserved in the database.

Requires: PostgreSQL running on localhost:5532 (see cookbook/scripts/run_pgvector.sh)
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.run.agent import RunEvent

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Storyteller",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a storyteller. Write very long detailed stories.",
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    store_tool_messages=True,
    store_history_messages=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_id = None
    cancelled = False
    content_chunks: list = []

    for event in agent.run(
        input="Write a very long story about a dragon who learns to code. Make it at least 2000 words.",
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
            agent.cancel_run(run_id)
            cancelled = True

        if hasattr(event, "event") and event.event == RunEvent.run_cancelled:
            print("\nRun was cancelled")
            break

    # Verify persistence
    print("\n--- Verification ---")
    session = agent.get_session(session_id=agent.session_id)
    if session and session.runs:
        last_run = session.runs[-1]
        print(f"Status: {last_run.status}")
        print(f"Content length: {len(last_run.content or '')}")
        print(f"Messages: {len(last_run.messages or [])}")
