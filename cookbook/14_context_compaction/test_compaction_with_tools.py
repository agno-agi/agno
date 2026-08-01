"""
Context Compaction Test with Tools and DB

Tests context compaction with:
- SQLite database for session persistence
- Web search tools to generate tool messages
- Small context window to trigger compaction quickly
- Debug logging enabled

Run: AGNO_DEBUG=true .venvs/demo/bin/python cookbook/14_context_compaction/test_compaction_with_tools.py
"""

import os

os.environ["AGNO_DEBUG"] = "true"

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# Small context window to trigger compaction quickly
CONTEXT_WINDOW = 8000

db = SqliteDb(db_file="tmp/dbs/context_compaction_test.db")

compression_manager = CompressionManager(
    model=OpenAIResponses(id="gpt-4o-mini"),
    compress_tool_results=False,
    context_compaction=True,
    context_window=CONTEXT_WINDOW,
    context_compaction_threshold=0.7,
    keep_recent_messages=4,
    user_message_budget_fraction=0.15,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    compression_manager=compression_manager,
    db=db,
    session_id="compaction-test-session",
    add_history_to_context=True,
    num_history_runs=20,
    debug_mode=True,
)

print("=" * 60)
print("Context Compaction Test")
print(f"Context window: {CONTEXT_WINDOW} tokens")
print(f"Threshold: 70% ({int(CONTEXT_WINDOW * 0.7)} tokens)")
print("=" * 60)

queries = [
    "Search for the latest news about OpenAI",
    "Search for Anthropic Claude updates",
    "Search for Google Gemini news",
]

for i, query in enumerate(queries, 1):
    print(f"\n[Turn {i}] {query}")
    print("-" * 40)

    response = agent.run(query)

    content = response.content or ""
    print(
        f"Response: {content[:200]}..."
        if len(content) > 200
        else f"Response: {content}"
    )

    print(f"\nCompression stats: {compression_manager.stats}")

print("\n" + "=" * 60)
print("Final Stats:")
print(f"  Compactions: {compression_manager.stats.get('compactions', 0)}")
print(f"  Messages compacted: {compression_manager.stats.get('messages_compacted', 0)}")
print("=" * 60)
