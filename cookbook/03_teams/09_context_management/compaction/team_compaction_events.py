"""
Team Compaction Events
=============================

A streamed Team run emits `TeamCompactionStarted` and `TeamCompactionCompleted`
when it folds, so a UI can show what happened to the context.

`TeamCompactionCompleted` carries how many messages were replaced, the token
count before and after, and whether the originals were archived.

The fold happens while the run's messages are assembled, before the model is
called. The two events come right after `TeamRunStarted`.

The questions below ask for long answers on purpose, so the conversation crosses
`compact_at_tokens` within a few turns.
"""

import asyncio

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.run.team import TeamRunEvent
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
explainer = Agent(
    name="Explainer",
    role="Explains messaging and queueing concepts in detail",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Messaging Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[explainer],
    db=db,
    session_id="team_compaction_events",
    add_history_to_context=True,
    instructions="Delegate each question to the Explainer and pass its answer on in full.",
    # A low threshold so a short demo folds by itself. team.compact() folds just as
    # well but has no run to emit events on.
    compaction=Compaction(compact_at_tokens=20_000, uncompacted_runs=1),
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def main():
    questions = [
        "Explain message queues in detail, with delivery guarantees and examples.",
        "Compare queues and topics in depth, covering fan-out and consumer groups.",
        "Explain at-least-once, at-most-once and exactly-once delivery in detail.",
        "Explain in detail how to make a consumer idempotent, with examples.",
        "Explain dead letter queues in detail: causes, handling and replay.",
    ]

    for question in questions:
        print(f"\n--- {question}")

        async for chunk in team.arun(question, stream=True, stream_events=True):
            if chunk.event == TeamRunEvent.run_started.value:
                print("[TeamRunStarted]")

            elif chunk.event == TeamRunEvent.compaction_started.value:
                print("[TeamCompactionStarted] the leader's context is being compacted")

            elif chunk.event == TeamRunEvent.compaction_completed.value:
                print(
                    f"[TeamCompactionCompleted] replaced {chunk.messages_compacted} messages"
                )
                if chunk.tokens_before and chunk.tokens_after:
                    saved = chunk.tokens_before - chunk.tokens_after
                    print(
                        f"  Tokens: {chunk.tokens_before} -> {chunk.tokens_after} (saved {saved})"
                    )
                if chunk.archived:
                    print("  Originals archived and searchable")

            elif chunk.event == TeamRunEvent.run_completed.value:
                print("[TeamRunCompleted]")


if __name__ == "__main__":
    asyncio.run(main())
