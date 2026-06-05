"""
Agno Demo — AgentOS Entrypoint
===============================

A demo AgentOS of wiki agents: one multimodal capability across three
backends. CodeSearch is left in as an example of a different kind of agent.

Agents
  LocalWiki    — read + write a local markdown wiki; ingest URLs or media
  GitWiki      — same agent, but the wiki is a git repo (env-gated)
  NotionWiki   — same agent, but the wiki is a Notion database (env-gated)
  CodeSearch   — answers questions about this repository (example agent)

Every agent runs on gpt-5.5 (see settings.py). The wiki agents are
multimodal — attach an image or PDF and they digest it and file a page.
(Swap settings.gemini_flash() in for an agent when you need audio or video.)
"""

from contextlib import asynccontextmanager
from pathlib import Path

from agents.code_search import code_search, code_search_provider
from agents.file_generator import file_generator
from agents.git_wiki import git_wiki, git_wiki_provider
from agents.local_wiki import local_wiki, local_wiki_provider
from agents.notion_wiki import notion_wiki, notion_wiki_provider
from agno.os import AgentOS
from agno.utils.log import log_info
from db import get_db


# ---------------------------------------------------------------------------
# Lifespan — close ContextProvider sessions on shutdown.
#
# `asetup()` is lazy on first query, so we don't pre-warm. `aclose()`
# on shutdown releases the underlying MCP sessions.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):  # type: ignore[no-untyped-def]
    log_info("AgentOS lifespan: startup")
    try:
        yield
    finally:
        log_info("AgentOS lifespan: shutdown — closing context providers")
        await local_wiki_provider.aclose()
        await code_search_provider.aclose()
        if git_wiki_provider is not None:
            await git_wiki_provider.aclose()
        if notion_wiki_provider is not None:
            await notion_wiki_provider.aclose()


# LocalWiki + CodeSearch are always on. GitWiki and NotionWiki register only
# when their backend credentials are set; they're appended after the
# always-on agents, so the optional wiki backends come last.
_agents = [local_wiki, code_search]
if git_wiki is not None:
    _agents.append(git_wiki)
if notion_wiki is not None:
    _agents.append(notion_wiki)


agent_os = AgentOS(
    name="Demo AgentOS",
    agents=_agents,
    db=get_db(),
    config=str(Path(__file__).parent / "config.yaml"),
    tracing=True,
    scheduler=True,
    scheduler_base_url="http://127.0.0.1:8000",
    lifespan=lifespan,
)

app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
