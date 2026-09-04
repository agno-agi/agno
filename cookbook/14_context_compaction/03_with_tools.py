"""
Context Compaction with Tools

Demonstrates compaction with tool-heavy workflows where tool results
consume significant context. User messages are preserved while tool
outputs are summarized.

Run: .venvs/demo/bin/python cookbook/14_context_compaction/03_with_tools.py
"""

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# Create compaction manager
compaction_manager = CompactionManager(
    model=OpenAIChat(id="gpt-4.1-mini"),
    compact_context=True,
    compact_context_message_limit=6,
    compact_context_keep_recent=2,
)

# Agent with web search tools - tool results can be large
agent = Agent(
    model=OpenAIChat(id="gpt-4.1-mini"),
    tools=[DuckDuckGoTools()],
    db=SqliteDb(db_file="tmp/tools_compaction.db"),
    session_id="tools-demo",
    add_history_to_context=True,
    compaction_manager=compaction_manager,
    markdown=True,
)

print("Running tool-heavy research session...")
print(
    "Context compaction will summarize tool results while preserving your questions.\n"
)

# Multi-turn research that generates large tool outputs
queries = [
    "Search for the latest news about Python 3.13 features",
    "Now search for TypeScript 5.0 new features",
    "Compare what you found - which has more impactful changes?",
]

for query in queries:
    print(f"User: {query}")
    response = agent.run(query)
    print(f"Assistant: {response.content[:300]}...")

    if response.compaction_state and response.compaction_state.total_compactions > 0:
        print(
            f"  [Compaction] {response.compaction_state.total_tokens_saved} tokens saved"
        )
    print()

# Show final compaction stats
if response.compaction_state and response.compaction_state.total_compactions > 0:
    state = response.compaction_state
    print("Final stats:")
    print(f"  Total compactions: {state.total_compactions}")
    print(f"  Tokens saved: {state.total_tokens_saved}")
