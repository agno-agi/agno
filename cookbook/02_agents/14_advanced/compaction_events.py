"""
Compaction Events
=================

Test script to verify context compaction events are working correctly.

Context compaction summarizes old conversation history when it exceeds limits,
emitting CompactionStarted and CompactionCompleted events.
"""

import asyncio

from agno.agent import Agent
from agno.compression.context import ContextCompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Agent with compaction enabled
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    description="Research assistant with context compaction",
    instructions="Help users research topics. Be thorough but concise.",
    db=SqliteDb(db_file="tmp/compaction_events_test.db"),
    add_history_to_context=True,
    # Enable context compaction with low threshold for testing
    compaction_manager=ContextCompactionManager(
        model=OpenAIResponses(id="gpt-5-mini"),
        message_limit=5,  # Low limit to trigger compaction quickly
        keep_recent=2,
    ),
)


async def main():
    print("--- Running agent with compaction events ---")
    print("This test runs multiple turns to trigger context compaction.\n")

    session_id = "compaction-events-test"

    # Run multiple turns to build up history and trigger compaction
    queries = [
        "What is the latest news about SpaceX?",
        "Tell me about recent Tesla developments.",
        "What's happening with Neuralink?",
        "Summarize what you've told me about Elon Musk's companies.",
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n{'=' * 60}")
        print(f"TURN {i}: {query}")
        print("=" * 60)

        stream = agent.arun(
            query,
            session_id=session_id,
            stream=True,
            stream_events=True,
        )

        async for chunk in stream:
            if chunk.event == RunEvent.run_started.value:
                print(f"[RunStarted] model={chunk.model}")

            elif chunk.event == RunEvent.compaction_started.value:
                print(f"[CompactionStarted] messages_before={chunk.messages_before}")
                print(f"  messages_to_compact={chunk.messages_to_compact}")

            elif chunk.event == RunEvent.compaction_completed.value:
                print(f"[CompactionCompleted] messages_after={chunk.messages_after}")
                print(f"  messages_compacted={chunk.messages_compacted}")
                print(f"  tokens_saved={chunk.tokens_saved}")
                if chunk.summary_preview:
                    print(f"  summary_preview={chunk.summary_preview[:100]}...")

            elif chunk.event == RunEvent.compression_started.value:
                print("[CompressionStarted] (tool results)")

            elif chunk.event == RunEvent.compression_completed.value:
                print(
                    f"[CompressionCompleted] compressed={chunk.tool_results_compressed} results"
                )

            elif chunk.event == RunEvent.tool_call_started.value:
                print(f"[ToolCallStarted] {chunk.tool.tool_name}")

            elif chunk.event == RunEvent.tool_call_completed.value:
                print(f"[ToolCallCompleted] {chunk.tool.tool_name}")

            elif chunk.event == RunEvent.run_completed.value:
                print("[RunCompleted]")
                if hasattr(chunk, "content") and chunk.content:
                    content = (
                        chunk.content[:200]
                        if len(chunk.content) > 200
                        else chunk.content
                    )
                    print(f"  Response: {content}...")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
