"""
Wiki Context Provider (filesystem + web ingestion)
==================================================

Same `WikiContextProvider` as `14_wiki_filesystem.py`, but with a
web backend wired in. The write sub-agent gets the workspace tools
plus `web_search` / `web_fetch` from `ExaMCPBackend` (keyless), so a
single `update_wiki(...)` call can fetch a URL or search the web,
digest the result, and file it as a wiki page.

The read sub-agent stays scoped to the wiki on purpose — "what does
the wiki say about X" should answer from the wiki, not silently
consult the web. Compose a separate `WebContextProvider` at the
outer agent if you want web on the read path.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from agno.agent import Agent
from agno.context.web import ExaMCPBackend
from agno.context.wiki import FileSystemBackend, WikiContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Seed an empty wiki directory next to the cookbook
# ---------------------------------------------------------------------------
WIKI_PATH = Path(__file__).resolve().parent / "demo-wiki-web"
if WIKI_PATH.exists():
    shutil.rmtree(WIKI_PATH)
WIKI_PATH.mkdir()
(WIKI_PATH / "README.md").write_text(
    "# Demo Wiki (with web ingestion)\n\n"
    "Pages live under `papers/`, `articles/`, and the root.\n"
)

# ---------------------------------------------------------------------------
# Create the provider — storage + web ingestion are two separate backends.
# ExaMCPBackend keyless is good enough for the demo; swap for ExaBackend
# or ParallelMCPBackend if you have keys.
# ---------------------------------------------------------------------------
wiki = WikiContextProvider(
    id="wiki",
    backend=FileSystemBackend(path=WIKI_PATH),
    web=ExaMCPBackend(),
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=wiki.get_tools(),
    instructions=wiki.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
async def _run() -> None:
    await wiki.asetup()
    try:
        print(f"\nwiki.status() = {wiki.status()}\n")

        ingest_prompt = (
            "Add a one-page summary of CPython's release schedule to "
            "papers/cpython-release-cycle.md. Search the web (python.org "
            "or PEP 602) for the source, digest it into a brief markdown "
            "page, and cite the URL in a Source section."
        )
        print(f"> {ingest_prompt}\n")
        await agent.aprint_response(ingest_prompt)

        print()
        read_prompt = (
            "What does the wiki say about CPython's release cycle? Cite the page."
        )
        print(f"> {read_prompt}\n")
        await agent.aprint_response(read_prompt)

        ingested = list(WIKI_PATH.glob("papers/*.md"))
        assert ingested, "agent did not file any pages under papers/"
        print(f"\n[ok] ingested {len(ingested)} page(s):")
        for p in ingested:
            print(f"     {p.relative_to(WIKI_PATH)} ({p.stat().st_size} bytes)")
    finally:
        await wiki.aclose()


if __name__ == "__main__":
    asyncio.run(_run())
