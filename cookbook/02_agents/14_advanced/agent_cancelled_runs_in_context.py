"""
Include Cancelled Runs in Context
=================================
Cancel an agent run mid-stream, then ask a follow-up question. With
add_cancelled_runs_to_context=True (alongside add_history_to_context=True),
the cancelled run's partial content is included in the history sent to the
model, so the agent still remembers what it was doing.

Requires: PostgreSQL running on localhost:5532 (see cookbook/scripts/run_pgvector.sh)
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Storyteller",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You are a storyteller. Write very long detailed stories.",
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    add_history_to_context=True,
    # Include the cancelled run's partial content in the history sent to the model.
    add_cancelled_runs_to_context=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "cancelled-context-demo"

    # Turn 1: start a story, then cancel it mid-stream
    run_id = None
    cancelled = False
    content_chunks: list = []
    for event in agent.run(
        input="Write a long story about a dragon named Ember who learns to code.",
        session_id=session_id,
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

    # Turn 2: the agent still remembers the interrupted story
    print("\n--- Follow-up turn ---")
    follow_up = agent.run(
        input="What was the dragon's name and what was she learning? Answer in one sentence.",
        session_id=session_id,
    )
    print(follow_up.content)
