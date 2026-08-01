"""
Realistic Context Compaction Test

10k token context window with a complex multi-step research task.
This simulates real-world usage where an agent does extended research.

Run: AGNO_DEBUG=true .venvs/demo/bin/python cookbook/14_context_compaction/test_realistic.py
"""

import os

os.environ["AGNO_DEBUG"] = "true"

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.playwright import PlaywrightTools

DB_PATH = "tmp/dbs/realistic_test.db"
SESSION_ID = "realistic-research-session"

# Realistic context window
CONTEXT_WINDOW = 10000
THRESHOLD = 0.8  # 80% = 8000 tokens before compaction


def main():
    print("=" * 70)
    print("Realistic Context Compaction Test")
    print(f"Context window: {CONTEXT_WINDOW} tokens")
    print(
        f"Threshold: {int(THRESHOLD * 100)}% ({int(CONTEXT_WINDOW * THRESHOLD)} tokens)"
    )
    print("=" * 70)

    db = SqliteDb(db_file=DB_PATH)

    compression_manager = CompressionManager(
        model=OpenAIResponses(id="gpt-4o-mini"),
        compress_tool_results=False,  # Disable tool compression to test pure context compaction
        context_compaction=True,
        context_compaction_threshold=THRESHOLD,
        context_window=CONTEXT_WINDOW,
        keep_recent_messages=6,
        user_message_budget_fraction=0.15,
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o"),
        tools=[PlaywrightTools(headless=True)],
        compression_manager=compression_manager,
        db=db,
        session_id=SESSION_ID,
        add_history_to_context=True,
        num_history_runs=50,
        instructions=[
            "You are a research assistant helping with competitive analysis.",
            "Be thorough and extract specific details from websites.",
        ],
    )

    # Complex multi-step research task
    task = """
    I need you to do competitive research on AI agent frameworks.

    1. First, visit https://github.com/langchain-ai/langchain and extract:
       - Number of stars
       - Main features listed in the README
       - Recent activity

    2. Then visit https://github.com/crewAIInc/crewAI and get the same info

    3. Finally visit https://github.com/agno-agi/agno and compare

    Give me a comparison table at the end.
    """

    print(f"\n[Complex Research Task]")
    print("-" * 70)
    print(task.strip())
    print("-" * 70)

    response = agent.run(task)

    print("\n[Response]")
    print("-" * 70)
    print(response.content)
    print("-" * 70)

    stats = compression_manager.stats
    print("\n" + "=" * 70)
    print("Compression Stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print("=" * 70)

    # Check if compaction happened
    compactions = stats.get("compactions", 0)
    if compactions > 0:
        print(f"\nSUCCESS: {compactions} compaction(s) occurred during research")
    else:
        print("\nNOTE: No compaction needed (context stayed under threshold)")


if __name__ == "__main__":
    # Clean start
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    main()
