"""
Web Readers: Website, YouTube, ArXiv, Firecrawl
=================================================
Readers for web-based content sources.

Supported web sources:
- WebsiteReader: Crawls web pages and extracts content
- YouTubeReader: Extracts transcripts from YouTube videos
- ArxivReader: Fetches academic papers from ArXiv
- FirecrawlReader: Advanced web scraping via Firecrawl API

See also: 01_documents.py for PDF/DOCX, 02_data.py for CSV/JSON.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.website_reader import WebsiteReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="web_readers",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- Website: crawl and extract content ---
        print("\n" + "=" * 60)
        print("READER: Website (crawl and extract)")
        print("=" * 60 + "\n")

        # WebsiteReader crawls pages up to max_depth and max_links
        website_reader = WebsiteReader(max_depth=1, max_links=5)
        await knowledge.ainsert(
            name="Agno Docs",
            url="https://docs.agno.com/introduction",
            reader=website_reader,
        )
        agent.print_response("What is Agno?", stream=True)

        # --- URL: direct URL loading (auto-detected) ---
        print("\n" + "=" * 60)
        print("READER: Direct URL (auto-detected)")
        print("=" * 60 + "\n")

        # URLs ending in .pdf, .md, .txt etc. are auto-detected
        await knowledge.ainsert(
            name="Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        )
        agent.print_response("What Thai recipes are available?", stream=True)

    asyncio.run(main())
