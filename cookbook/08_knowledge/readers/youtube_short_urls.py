"""Load YouTube transcripts from short URLs (youtu.be format).

Many users share YouTube videos using short URLs from:
- Mobile app share button
- Twitter/X posts
- Slack messages
- Text messages

This cookbook demonstrates loading transcripts from youtu.be URLs.

Run: `python cookbook/08_knowledge/readers/youtube_short_urls.py`
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.youtube_reader import YouTubeReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


async def main():
    knowledge = Knowledge(
        vector_db=PgVector(table_name="youtube_short_urls", db_url=db_url),
    )

    reader = YouTubeReader()

    # Videos shared from different sources
    videos = [
        # Standard format (from desktop browser)
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Desktop Share"),
        # Short format (from mobile app)
        ("https://youtu.be/dQw4w9WgXcQ", "Mobile Share"),
        # Short format with timestamp (from Slack)
        ("https://youtu.be/dQw4w9WgXcQ?t=60", "Slack Share"),
    ]

    print("Loading YouTube videos from various URL formats...")
    print("-" * 50)

    for url, source in videos:
        print(f"\nSource: {source}")
        print(f"URL: {url}")

        documents = await reader.async_read(url=url, name=source)

        if documents:
            print(f"Loaded {len(documents)} document(s)")
            await knowledge.ainsert(documents=documents)
        else:
            print("Failed to load (no documents returned)")

    # Query the knowledge base
    agent = Agent(
        knowledge=knowledge,
        search_knowledge=True,
    )

    print("\n" + "-" * 50)
    print("Querying knowledge base...")
    agent.print_response("What videos are in the knowledge base?", markdown=True)


if __name__ == "__main__":
    asyncio.run(main())
