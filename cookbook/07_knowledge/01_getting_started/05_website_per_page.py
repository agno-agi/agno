"""
Website Ingestion: One Row Per Page
===================================
Load a website into a knowledge base page by page from its sitemap:
one content row per page with its source URL kept, so the agent can
cite the page it answered from and a re-run refreshes only pages
that changed.

SitemapReader discovers pages from the site's sitemap (robots.txt and
sitemap indexes are followed) and fetches each page whole. Pages land
as separate rows on the Knowledge page; deleting the site row removes
every page and its vectors.

A bare sitemap URL selects this reader automatically:
    await knowledge.ainsert(url="https://docs.agno.com/sitemap.xml")
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.sitemap_reader import SitemapReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Create Knowledge
# ---------------------------------------------------------------------------
# The contents db is what holds the per-page rows (and the digests that make
# re-ingest refresh only changed pages) — without it, only vectors are stored.
knowledge = Knowledge(
    name="Agno Docs",
    contents_db=SqliteDb(db_file="tmp/agno_docs_contents.db"),
    vector_db=Qdrant(
        collection="website-pages",
        url="http://localhost:6333",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions="Answer from the knowledge base and cite the source URL of the page you used.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
async def main() -> None:
    # One call: sitemap discovery, page-by-page fetch, one row per page.
    # Uses Parallel's extraction when PARALLEL_API_KEY or the mcp extra is
    # available, the built-in fetcher otherwise.
    await knowledge.ainsert(
        url="https://docs.agno.com",
        reader=SitemapReader(max_pages=25),
    )

    await agent.aprint_response("What is an Agent in Agno? Cite the page you used.")


if __name__ == "__main__":
    asyncio.run(main())
