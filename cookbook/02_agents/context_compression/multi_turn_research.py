"""
Multi-turn research agent with context compression.
Tests fact preservation across conversation turns.

This cookbook validates that context compression:
1. Preserves exact numbers (revenue, percentages, dates)
2. Maintains facts from earlier turns during incremental merging
3. Allows the agent to synthesize information from compressed history

Run: .venvs/demo/bin/python cookbook/02_agents/context_compression/multi_turn_research.py
"""

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# Create compression manager with custom settings
# compress_context_messages_limit=6 triggers compression after 6 non-system messages
compression_manager = CompressionManager(
    model=OpenAIChat(id="gpt-5-mini"),
    compress_context=True,
    compress_context_messages_limit=6,
)

# Create agent with context compression enabled
agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    description="Investment research analyst",
    instructions=[
        "You are an investment research analyst.",
        "Always cite specific numbers: revenue, profit, market cap, P/E ratios.",
        "When comparing companies, create a structured comparison.",
        "Use the search tools to find the latest financial data.",
    ],
    # Pass the compression manager
    compression_manager=compression_manager,
    # Session persistence (to test across turns)
    db=SqliteDb(db_file="tmp/dbs/multi_turn_research.db"),
    session_id="research_session_002",  # Fresh session
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# Multi-turn research conversation
turns = [
    "Search for Apple's Q3 2024 financial results. Find the exact revenue and profit numbers.",
    "Now search for Microsoft's Q3 2024 financials. Compare their revenue with Apple's.",
    "What are the current P/E ratios for both Apple and Microsoft?",
    "Based on everything you found, which company had better financial performance in Q3 2024?",
]


def run_turn(prompt: str, turn_num: int) -> None:
    """Run a single turn and display compression info."""
    print(f"\n{'='*70}")
    print(f"TURN {turn_num}: {prompt[:60]}...")
    print("=" * 70)

    # Run the agent (print_response handles content streaming)
    agent.print_response(prompt, stream=True)

    # After the turn, check compression stats and context
    print("\n")

    # Show compression manager stats
    stats = compression_manager.stats
    if stats:
        print("-" * 70)
        print("COMPRESSION STATS:")
        print(f"  Context compressions: {stats.get('context_compressions', 0)}")
        print(f"  Messages compressed: {stats.get('messages_compressed', 0)}")
        original_tokens = stats.get("original_context_tokens", 0)
        compressed_tokens = stats.get("compression_context_tokens", 0)
        if original_tokens:
            print(f"  Token reduction: {original_tokens} -> {compressed_tokens}")
            ratio = (1 - compressed_tokens / original_tokens) * 100
            print(f"  Compression ratio: {ratio:.1f}% reduction")
        print("-" * 70)

    # Check if we have compressed context in session
    session = agent.get_session()
    if session:
        compression_ctx = session.get_compression_context()
        if compression_ctx:
            print("\nCURRENT COMPRESSED CONTEXT:")
            print("-" * 70)
            # Show first 1000 chars to see what's being preserved
            content = compression_ctx.content
            if len(content) > 1000:
                print(content[:1000] + "\n... [truncated]")
            else:
                print(content)
            print(f"\nMessages compressed so far: {len(compression_ctx.message_ids)}")
            print("-" * 70)


def main():
    print("=" * 70)
    print("MULTI-TURN RESEARCH AGENT - CONTEXT COMPRESSION TEST")
    print("=" * 70)
    print("\nThis test validates that context compression preserves:")
    print("  - Exact financial numbers (revenue, profit)")
    print("  - Company comparisons across turns")
    print("  - Facts needed for final synthesis")
    print("\nCompression triggers after 6 non-system messages in context.\n")

    for i, prompt in enumerate(turns, 1):
        run_turn(prompt, i)

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    print("\nCheck the compressed context above to verify:")
    print("  1. Are exact numbers preserved (not rounded)?")
    print("  2. Are facts from ALL turns present?")
    print("  3. Could the agent answer questions using only the compressed context?")


if __name__ == "__main__":
    main()
