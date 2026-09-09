"""
SSRF Hardening: allowed_hosts on URL-fetching Readers
=======================================================
Knowledge readers that fetch arbitrary URLs (WebsiteReader, FirecrawlReader,
DoclingReader, LLMsTxtReader, WebSearchReader) accept an opt-in `allowed_hosts`
argument that restricts outbound requests to a hostname allowlist.

This matters in production for two reasons:

1. AgentOS exposes `POST /knowledge/content`, which accepts a URL and schedules
   a background fetch. Without an allowlist, an attacker can target internal
   services.

2. The allowlist also runs on every redirect target via an httpx request hook,
   so a permitted host cannot 3xx-bounce the request to an internal address.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.website_reader import WebsiteReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.lancedb import LanceDb, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
#
# LanceDB runs in-process and persists to a local directory, so this cookbook
# needs no additional services (no `run_qdrant.sh`, no docker).

knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb_ssrf_demo",
        table_name="ssrf_allowed_hosts_demo",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # -------------------------------------------------------------------
        # 1. Allowed host: ingestion proceeds normally
        # -------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("CASE 1: URL in allowed_hosts -> ingested")
        print("=" * 60 + "\n")

        reader = WebsiteReader(
            max_depth=1,
            max_links=5,
            allowed_hosts=["docs.agno.com"],
        )
        await knowledge.ainsert(
            name="Agno Docs",
            url="https://docs.agno.com/introduction",
            reader=reader,
        )
        agent.print_response("What is Agno?", stream=True)

        # -------------------------------------------------------------------
        # 2. Disallowed host: ingestion short-circuits, no request fires
        # -------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("CASE 2: URL outside allowed_hosts -> refused (no fetch)")
        print("=" * 60 + "\n")

        # Same reader instance. Common SSRF targets: localhost services,
        # RFC1918 ranges, the cloud metadata endpoint at 169.254.169.254.
        for ssrf_target in (
            "http://127.0.0.1:8000/admin",
            "http://10.0.0.5/internal",
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        ):
            documents = reader.read(ssrf_target)
            print(f"  {ssrf_target} -> {len(documents)} documents (refused)")

        # -------------------------------------------------------------------
        # 3. Default behavior: no allowlist = no policy
        # -------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("CASE 3: No allowed_hosts -> permissive (legacy behavior)")
        print("=" * 60 + "\n")

        permissive_reader = WebsiteReader(max_depth=1, max_links=2)
        print(f"  allowed_hosts is {permissive_reader.allowed_hosts}")
        print("  Any reachable URL would be fetched.")

        # -------------------------------------------------------------------
        # 4. Same knob exists on the other URL-fetching readers
        # -------------------------------------------------------------------

        #   from agno.knowledge.reader.firecrawl_reader import FirecrawlReader
        #   FirecrawlReader(api_key=..., allowed_hosts=["docs.agno.com"])
        #
        #   from agno.knowledge.reader.docling_reader import DoclingReader
        #   DoclingReader(allowed_hosts=["docs.agno.com"])
        #
        #   from agno.knowledge.reader.llms_txt_reader import LLMsTxtReader
        #   LLMsTxtReader(allowed_hosts=["docs.agno.com"])
        #
        #   from agno.knowledge.reader.web_search_reader import WebSearchReader
        #   WebSearchReader(allowed_hosts=["docs.agno.com", "github.com"])

    asyncio.run(main())
