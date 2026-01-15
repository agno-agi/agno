"""This cookbook shows how to load YouTube transcripts asynchronously.

YouTubeReader supports both sync and async methods with the same API:
- read(url, name="Custom Name") - synchronous
- async_read(url, name="Custom Name") - asynchronous

Both methods accept an optional name parameter to customize the document name.

Run: `python cookbook/08_knowledge/readers/youtube_transcript_async.py`
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.youtube_reader import YouTubeReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


async def main():
    knowledge = Knowledge(
        vector_db=PgVector(table_name="youtube_async_example", db_url=db_url),
    )

    reader = YouTubeReader()

    # Example video URL
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    custom_name = "Classic Music Video"

    print("Loading YouTube video asynchronously...")
    print(f"  URL: {video_url}")
    print(f"  Custom name: {custom_name}")

    try:
        # Load transcript with custom name using async method
        documents = await reader.async_read(
            url=video_url,
            name=custom_name,
        )

        if documents:
            print(f"\nLoaded {len(documents)} document(s)")
            for doc in documents:
                print(f"  Document name: {doc.name}")

            await knowledge.ainsert(documents=documents)
        else:
            print("\nNo transcript available (video may not have captions)")

    except Exception as e:
        print(f"\nNote: {e}")
        print("(This may be a network/API issue)")

    # Create agent and query
    agent = Agent(
        knowledge=knowledge,
        search_knowledge=True,
    )

    print("\nQuerying the knowledge base...")
    agent.print_response(
        "What content was loaded?",
        markdown=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
