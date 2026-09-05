"""Public page-backed chat, Team, native MCP, and protected source synchronization.

Run with .venvs/demo/bin/python; see README.md for database and credential setup.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import PageError, tool_error
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig
from agno.os.public import PublicSurface
from agno.team import Team
from agno.tools.mcp import MCPTools
from agno.vectordb.pgvector import PgVector
from agno.workflow import Step, StepInput, StepOutput, Workflow
from pydantic import BaseModel, Field

# Separate demo database; do not point this example at production tables.
db = PostgresDb(
    db_url=getenv(
        "PAGE_DEMO_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/page_demo"
    )
)
knowledge = Knowledge(
    content_db=db,
    page_store=FileSystem(
        db,
        namespace="public-page-demo",
        max_file_bytes=4 * 1024 * 1024,
        max_namespace_bytes=256 * 1024 * 1024,
    ),
    vector_db=PgVector(
        db_engine=db.db_engine,
        table_name="demo_page_vectors",
        embedder=OpenAIEmbedder(
            id="text-embedding-3-small",
            dimensions=1536,
            client_params={"timeout": 20, "max_retries": 0},
        ),
    ),
)
index_url = getenv("PAGE_DEMO_INDEX_URL", "https://docs.agno.com/llms.txt")


# Explicit names and descriptions customize the tool surface using public APIs.
async def search_docs(query: str) -> str:
    """Search published documentation sections. Cite their returned URLs."""
    try:
        return (await knowledge.asearch_pages(query)).model_dump_json()
    except (PageError, ValueError) as exc:
        return tool_error(exc)


async def read_docs(path: str, offset: int = 0) -> str:
    """Read a full page, continuing with next_offset when present."""
    try:
        return (await knowledge.aread_page(path, offset=offset)).model_dump_json()
    except (PageError, ValueError) as exc:
        return tool_error(exc)


async def grep_docs(query: str, prefix: str = "/") -> str:
    """Find literal text. An incomplete result does not establish absence."""
    try:
        return (await knowledge.agrep_pages(query, prefix=prefix)).model_dump_json()
    except (PageError, ValueError) as exc:
        return tool_error(exc)


tools = [search_docs, read_docs, grep_docs]
agent = Agent(
    id="docs",
    name="Docs",
    model=OpenAIResponses(id="gpt-5.6-luna", store=False, timeout=60),
    db=db,
    knowledge=knowledge,
    add_knowledge_to_context=True,
    search_knowledge=False,
    tools=tools,
    instructions="Answer from the documentation. Cite returned URLs beside claims.",
    markdown=True,
    telemetry=False,
)
researcher = Agent(
    id="researcher",
    model=OpenAIResponses(id="gpt-5.6-luna", store=False, timeout=60),
    knowledge=knowledge,
    tools=tools,
    search_knowledge=False,
    telemetry=False,
)
team = Team(
    id="docs-team",
    name="Docs team",
    members=[researcher],
    db=db,
    model=OpenAIResponses(id="gpt-5.6-luna", store=False, timeout=60),
    instructions="Use your researcher to answer documentation questions with source URLs.",
    telemetry=False,
)


class SyncRequest(BaseModel):
    reason: str = Field(default="manual", max_length=1000)
    reindex: bool = False


async def sync_source(step_input: StepInput) -> StepOutput:
    request = SyncRequest.model_validate(step_input.input or {})
    result = await knowledge.async_sync_pages(url=index_url, reindex=request.reindex)
    return StepOutput(content=result.model_dump(), success=result.status != "partial")


sync = Workflow(
    id="sync-docs",
    name="Sync docs",
    db=db,
    input_schema=SyncRequest,
    steps=[Step(name="reconcile", executor=sync_source)],
)


@asynccontextmanager
async def prepare(app):
    await knowledge.asetup()
    yield


agent_os = AgentOS(
    id="public-page-demo",
    db=db,
    agents=[agent],
    teams=[team],
    workflows=[sync],
    # url=None reads AGENTOS_URL. Explicit overrides below win over derived URLs.
    url=None,
    scheduler_base_url=getenv("PAGE_DEMO_SCHEDULER_URL"),
    internal_service_token=getenv("PAGE_DEMO_SYNC_TOKEN"),
    public=PublicSurface(agents=[agent], teams=[team], workflows=[sync], mcp=True),
    mcp=MCPConfig(
        tools=tools,
        default_tools=False,
        lifecycle_tools=False,
        stateless=True,
        server_card_url=getenv("PAGE_DEMO_MCP_URL"),
        allowed_hosts=["localhost:*", "127.0.0.1:*"],
        instructions="Use search_docs for discovery, then read_docs or grep_docs for exact evidence.",
    ),
    cors_allowed_origins=["http://localhost:3000"],
    lifespan=prepare,
    telemetry=False,
)
app = agent_os.get_app()


async def command(mode: str) -> None:
    if mode == "mcp-client":
        base = agent_os.url or "http://localhost:7777"
        async with MCPTools(url=base + "/mcp", transport="streamable-http") as mcp:
            print(
                await mcp.session.call_tool(
                    "search_docs", {"query": "Agent with tools"}
                )
            )
        return
    await knowledge.asetup()
    if mode == "sync":
        print((await knowledge.async_sync_pages(url=index_url)).model_dump_json())
        pages = await knowledge.alist_pages(limit=1)
        if pages.pages:
            print((await knowledge.aread_page(pages.pages[0].path)).model_dump_json())
            print((await knowledge.agrep_pages("Agent")).model_dump_json())
    else:
        await agent.aprint_response(
            "How do I create an agent with tools? Cite the documentation.", stream=True
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["sync", "chat", "serve", "mcp-client"])
    args = parser.parse_args()
    if args.mode == "serve":
        agent_os.serve(app=app, host="127.0.0.1", port=7777)
    else:
        asyncio.run(command(args.mode))
