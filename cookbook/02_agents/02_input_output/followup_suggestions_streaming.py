"""
Followups — Streaming
=====================

Stream the main response token-by-token and capture followup suggestions
via events at the end.

Key concepts:
- stream=True, stream_events=True: enables streaming with events
- RunEvent.run_content: tokens of the main response
- RunEvent.followups_completed: carries the finished followup suggestions
"""

import asyncio

from agno.agent import Agent, RunEvent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

db = SqliteDb(db_file="tmp/agents.db")

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    instructions="You are a knowledgeable assistant. Answer questions thoroughly.",
    session_id="test-session",
    followups=True,
    num_followups=3,
    markdown=True,
    db=db,
    add_history_to_context=True,
)


# ---------------------------------------------------------------------------
# Stream the response and capture followups from events
# ---------------------------------------------------------------------------
async def main():
    content_started = False
    async for event in agent.arun(
        "Which national park is the best?",
        stream=True,
        stream_events=True,
    ):
        # Stream response tokens
        if event.event == RunEvent.run_content:
            if not content_started:
                print("Response:")
                print("=" * 60)
                content_started = True
            if event.content:
                print(event.content, end="", flush=True)

        # Followups arrive as a single completed event
        if event.event == RunEvent.followups_completed:
            print(f"\n\n{'=' * 60}")
            print("Followups:")
            print("=" * 60)
            if event.followups:  # type: ignore
                for i, suggestion in enumerate(event.followups, 1):  # type: ignore
                    print(f"  {i}. {suggestion}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
