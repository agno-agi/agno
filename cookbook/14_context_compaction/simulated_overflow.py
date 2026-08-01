"""
Simulated Context Overflow

Demonstrates context compaction with a small context window to trigger
compaction without needing a very long conversation. Uses search tools
to generate more context per turn.

Run: AGNO_DEBUG=true .venvs/demo/bin/python cookbook/14_context_compaction/simulated_overflow.py
"""

import os

os.environ["AGNO_DEBUG"] = "true"

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# Small context window to trigger compaction quickly
SIMULATED_CONTEXT_WINDOW = 4000  # ~1000 words

db = SqliteDb(db_file="tmp/dbs/context_overflow_test.db")

# Custom compression manager for demo with lower threshold
compression_manager = CompressionManager(
    model=OpenAIResponses(id="gpt-4o-mini"),
    context_compaction=True,
    context_compaction_threshold=0.4,  # Trigger at 40% for demo (1600 tokens)
    context_window=SIMULATED_CONTEXT_WINDOW,
    keep_recent_messages=4,
    user_message_budget_fraction=0.15,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    compression_manager=compression_manager,
    db=db,
    session_id="overflow-demo-with-db",
    add_history_to_context=True,
    num_history_runs=20,
)


def print_separator():
    print("-" * 60)


print("Context Compaction Demo (small context window)")
print(f"Context window: {SIMULATED_CONTEXT_WINDOW} tokens")
print(f"Threshold: 70% ({int(SIMULATED_CONTEXT_WINDOW * 0.7)} tokens)")
print("=" * 60)

# Build up conversation history with search queries to accumulate context faster
prompts = [
    "Search for recent news about OpenAI GPT-5",
    "Search for latest developments in Anthropic Claude",
    "Search for Google Gemini AI updates",
    "Search for latest AI research breakthroughs",
]

for i, prompt in enumerate(prompts, 1):
    print(f"\n[Turn {i}] User: {prompt}")
    print_separator()

    response = agent.run(prompt)

    # Show truncated response
    content = response.content or ""
    if len(content) > 300:
        print(f"Assistant: {content[:300]}...")
    else:
        print(f"Assistant: {content}")

    # Show stats after each turn
    if compression_manager.stats.get("compactions", 0) > 0:
        print_separator()
        print(
            f"[Compaction occurred! Total: {compression_manager.stats['compactions']}]"
        )
        print(
            f"  Messages compacted: {compression_manager.stats.get('messages_compacted', 0)}"
        )

print("\n" + "=" * 60)
print("Final Stats:")
for key, value in compression_manager.stats.items():
    print(f"  {key}: {value}")
