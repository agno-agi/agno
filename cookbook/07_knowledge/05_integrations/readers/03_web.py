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

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.website_reader import WebsiteReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="web_readers",
        db_url=db_url,
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
    # --- Website: crawl and extract content ---
    print("\n" + "=" * 60)
    print("READER: Website (crawl and extract)")
    print("=" * 60 + "\n")

    # WebsiteReader crawls pages up to max_depth and max_links
    website_reader = WebsiteReader(max_depth=1, max_links=5)
    knowledge.insert(
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
    knowledge.insert(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    )
    agent.print_response("What Thai recipes are available?", stream=True)
