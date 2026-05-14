"""
Agno Demo — AgentOS Entrypoint
===============================

Agents
  LocalWiki   — read + write a local markdown wiki, ingest URLs via Parallel MCP
  GitWiki     — same, but pushes to a git remote (env-gated)
  WebSearch   — keyless web research via Parallel MCP
  CodeSearch  — answers questions about this repository
  Researcher  — composes web + local_wiki + code_search on one agent

Teams
  Swarm       — broadcast: two web-search agents (OpenAI + Anthropic),
                leader synthesizes both views

Workflows
  Brief       — sequential: WebSearch → LocalWiki, files a brief to the wiki
"""

from contextlib import asynccontextmanager
from pathlib import Path

from agents.code_search import code_search, code_search_provider
from agents.git_wiki import git_wiki, git_wiki_provider
from agents.local_wiki import local_wiki, local_wiki_provider
from agents.researcher import researcher
from agents.web_search import web_provider, web_search
from agno.os import AgentOS
from agno.utils.log import log_info
from db import get_db
from teams.swarm import swarm
from workflows.brief import brief


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
        await web_provider.aclose()
        await code_search_provider.aclose()
        if git_wiki_provider is not None:
            await git_wiki_provider.aclose()


# GitWiki is conditional on WIKI_REPO_URL + WIKI_GITHUB_TOKEN.
_agents = [local_wiki, web_search, code_search, researcher]
if git_wiki is not None:
    _agents.insert(1, git_wiki)


agent_os = AgentOS(
    name="Demo AgentOS",
    agents=_agents,
    teams=[swarm],
    workflows=[brief],
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
