"""
Heavy Browser Context Test

Uses PlaywrightTools to generate heavy context through web scraping.
Browser tools return full page content, triggering compaction quickly.

Requires:
    pip install playwright
    playwright install chromium

Run: AGNO_DEBUG=true .venvs/demo/bin/python cookbook/14_context_compaction/test_browser_heavy.py
"""

import os
import sys

os.environ["AGNO_DEBUG"] = "true"

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.playwright import PlaywrightTools

DB_PATH = "tmp/dbs/browser_heavy_test.db"
SESSION_ID = "browser-heavy-session"

# Low threshold to trigger compaction with heavy browser content
CONTEXT_WINDOW = 4000
THRESHOLD = 0.3  # 30% = 1200 tokens


def main():
    print("=" * 60)
    print("Browser Heavy Context Test")
    print(f"Context window: {CONTEXT_WINDOW} tokens")
    print(
        f"Threshold: {int(THRESHOLD * 100)}% ({int(CONTEXT_WINDOW * THRESHOLD)} tokens)"
    )
    print("=" * 60)

    db = SqliteDb(db_file=DB_PATH)

    compression_manager = CompressionManager(
        model=OpenAIResponses(id="gpt-4o-mini"),
        context_compaction=True,
        context_compaction_threshold=THRESHOLD,
        context_window=CONTEXT_WINDOW,
        keep_recent_messages=4,
        user_message_budget_fraction=0.15,
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[PlaywrightTools(headless=True)],
        compression_manager=compression_manager,
        db=db,
        session_id=SESSION_ID,
        add_history_to_context=True,
        num_history_runs=20,
    )

    # URLs that return substantial content
    tasks = [
        "Visit https://news.ycombinator.com and extract the top 10 story titles",
        "Visit https://quotes.toscrape.com and extract the first 5 quotes with authors",
        "Visit https://books.toscrape.com and list the first 5 book titles with prices",
    ]

    for i, task in enumerate(tasks, 1):
        print(f"\n[Task {i}] {task[:50]}...")
        print("-" * 40)

        try:
            response = agent.run(task)
            content = response.content or ""
            print(f"Response: {content[:150]}...")

            stats = agent.compression_manager.stats
            compactions = stats.get("compactions", 0)
            if compactions > 0:
                print(f"  -> Compactions: {compactions}")
                print(f"  -> Messages compacted: {stats.get('messages_compacted', 0)}")
        except Exception as e:
            print(f"Error: {e}")

    print("\n" + "=" * 60)
    print("Final Stats:")
    for key, value in agent.compression_manager.stats.items():
        print(f"  {key}: {value}")
    print("=" * 60)

    # Verify DB persistence
    from sqlite3 import connect

    conn = connect(DB_PATH)
    cursor = conn.execute(
        "SELECT json_extract(session_data, '$.context_compaction') FROM agno_sessions WHERE session_id = ?",
        (SESSION_ID,),
    )
    row = cursor.fetchone()
    if row and row[0]:
        print("\nPersisted compaction state found in DB")
    conn.close()


if __name__ == "__main__":
    # Clean start
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    main()
