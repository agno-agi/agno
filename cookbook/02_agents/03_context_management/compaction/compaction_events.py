"""
Compaction Events
=============================

Compaction emits `CompactionStarted` and `CompactionCompleted` on a streaming
run, so a UI can show what happened to the context instead of silently losing
turns.

`CompactionCompleted` carries how many messages were replaced, the token count
before and after, and where the originals were archived.

Note these arrive during message assembly, before the model is called - so they
land near the start of a run, ahead of the first `ModelRequestStarted`.

The questions below ask for long answers on purpose. A summary has a floor cost,
so `min_fold_ratio` (2.0 by default) skips a fold that would not be meaningfully
larger than the tail it keeps - folding a handful of one-line turns would leave
the context bigger than it started.
"""

import asyncio

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction_events.db"),
    session_id="compaction_events",
    add_history_to_context=True,
    num_history_runs=100,
    # Low thresholds so a short demo actually triggers a compaction.
    compaction=Compaction(compact_at_runs=4, keep_last_runs=2),
)


async def main():
    questions = [
        "Explain message queues in detail, with delivery guarantees and examples.",
        "Compare queues and topics in depth, covering fan-out and consumer groups.",
        "Explain at-least-once, at-most-once and exactly-once delivery in detail.",
        "Explain in detail how to make a consumer idempotent, with examples.",
        "Explain dead letter queues in detail: causes, handling and replay.",
        "Explain backpressure strategies in detail, with trade-offs.",
    ]

    for question in questions:
        print(f"\n--- {question}")

        async for chunk in agent.arun(question, stream=True, stream_events=True):
            if chunk.event == RunEvent.compaction_started.value:
                print("[CompactionStarted] context is being compacted")

            elif chunk.event == RunEvent.compaction_completed.value:
                print(
                    f"[CompactionCompleted] replaced {chunk.messages_compacted} messages"
                )
                if chunk.tokens_before and chunk.tokens_after:
                    saved = chunk.tokens_before - chunk.tokens_after
                    reduction = (1 - chunk.tokens_after / chunk.tokens_before) * 100
                    print(
                        f"  Tokens: {chunk.tokens_before} -> {chunk.tokens_after} (saved {saved}, {reduction:.1f}%)"
                    )
                if chunk.archived:
                    print("  Originals archived and searchable")

            elif chunk.event == RunEvent.run_completed.value:
                print("[RunCompleted]")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
