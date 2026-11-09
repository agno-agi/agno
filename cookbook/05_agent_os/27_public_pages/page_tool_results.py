"""Inspect typed page results and configure matching chat/MCP tools."""

import argparse
import asyncio

from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import PageFileSystem
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)
knowledge = Knowledge(
    content_db=db,
    page_store=FileSystem(db=db, namespace="page-tool-results-demo"),
    vector_db=PgVector(
        db=db,
        table_name="page_tool_results_vectors",
        embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
    ),
)

# A small source; sync publishes every page it discovers and embeds each chunk.
index_url = "https://better-auth.com/docs/llms.txt"


async def sync() -> None:
    """Publish the example corpus the commands below read."""
    await knowledge.asetup()
    print((await knowledge.async_sync_pages(url=index_url)).model_dump_json())


async def run(command: str) -> None:
    """Run one page command and show the typed result its caller receives."""
    await knowledge.asetup()
    files = PageFileSystem(knowledge=knowledge)

    result = await files.arun_command_result(command, max_output_bytes=24000)
    print(result.model_dump_json(indent=2))

    # Error status comes from execution, so a page about errors stays successful.
    missing = await files.arun_command_result("cat /no-such-page")
    print(f"\nmissing page -> is_error={missing.is_error} errors={missing.errors}")

    # Supply these explicitly to Agent.tools and MCPConfig.tools respectively.
    chat_search = knowledge.get_tools(page_results=True, tool_name="search_docs")
    mcp_search = knowledge.get_tools(
        page_results=True, tool_name="search_docs", transport="mcp", async_mode=True
    )
    mcp_files = files.tools(tool_name="query_docs_filesystem", transport="mcp")
    print(f"tools ready: {len(chat_search + mcp_search + [mcp_files])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", nargs="?", default="check", choices=["check", "sync", "run"]
    )
    parser.add_argument("command", nargs="?", default="ls /")
    args = parser.parse_args()
    if args.mode == "check":
        print("Page tool results configuration validated.")
    elif args.mode == "sync":
        asyncio.run(sync())
    else:
        asyncio.run(run(args.command))
