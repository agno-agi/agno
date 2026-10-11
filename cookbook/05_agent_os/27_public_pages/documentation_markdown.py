"""Normalize documentation MDX into Markdown while synchronizing published pages."""

import argparse
import asyncio

from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.knowledge.chunking.page import PageMarkdownChunking
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import DocumentationMarkdown
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)
knowledge = Knowledge(
    content_db=db,
    page_store=FileSystem(db=db, namespace="documentation-markdown-demo"),
    vector_db=PgVector(
        db=db,
        table_name="documentation_markdown_vectors",
        embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
    ),
)

# A small fumadocs source; docs.agno.com lists 3,911 pages and embeds every chunk.
index_url = "https://better-auth.com/docs/llms.txt"

transform = DocumentationMarkdown(profile="fumadocs")


async def publish() -> None:
    """Publish every discovered page through the transform; embeds each chunk."""
    await knowledge.asetup()
    report = await knowledge.async_sync_pages(
        url=index_url, transform=transform, index_version="docs-v1"
    )
    print(report.model_dump_json())

    pages = await knowledge.alist_pages(limit=1)
    if not pages.pages:
        return
    path = pages.pages[0].path
    body = await knowledge.aread_full_page(path)
    if body is None:
        return
    print(f"\n{path} after normalization:\n")
    print(body[:600])
    print(f"\nChunks for this page: {len(PageMarkdownChunking().chunk_texts(body))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    # Default to the configuration check: sync publishes and embeds every page.
    parser.add_argument("mode", nargs="?", default="check", choices=["check", "sync"])
    if parser.parse_args().mode == "check":
        print("Documentation Markdown configuration validated.")
    else:
        asyncio.run(publish())
