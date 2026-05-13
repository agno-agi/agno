"""
GitWiki Agent (env-gated)
=========================

Same as LocalWiki, but the wiki lives in a real git repository.
After every write, the backend stages, commits with an LLM-summarised message, rebases onto the remote, and pushes.

Env-gated: registered in AgentOS only when both ``WIKI_REPO_URL`` and ``WIKI_GITHUB_TOKEN`` are set. Otherwise the module exports ``None`` and ``run.py`` skips it.

Required env:
  WIKI_REPO_URL       (https://github.com/<owner>/<repo>.git)
  WIKI_GITHUB_TOKEN   (PAT with contents:write on that repo)

Optional env:
  WIKI_BRANCH         (default: main)
  WIKI_LOCAL_PATH     (default: ./data/git-wiki/ next to this cookbook)
"""

from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.context.web import ParallelMCPBackend
from agno.context.wiki import GitBackend, WikiContextProvider
from db import get_db
from settings import default_model, sub_agent_model

_REPO_URL = getenv("WIKI_REPO_URL")
_TOKEN = getenv("WIKI_GITHUB_TOKEN")
_BRANCH = getenv("WIKI_BRANCH", "main")
_LOCAL_PATH = getenv("WIKI_LOCAL_PATH") or str(
    Path(__file__).resolve().parents[1] / "data" / "git-wiki"
)


GIT_WIKI_INSTRUCTIONS = """\
You curate a git-backed markdown wiki. Two things you do:

1. Answer "what does the wiki say about X" — call query_git_wiki
   and quote the page. If the wiki is silent, say so plainly.
2. Ingest sources into the wiki — when asked to "add", "save",
   "file", or "ingest" a URL or topic, call update_git_wiki. The
   backend auto-commits and pushes after each write, so keep
   commit-worthy notes in mind.
"""


# Only construct the provider/agent when credentials are available.
# Importing modules that read env at construction time still need to
# handle the disabled case — see run.py and evals/cases.py.
if _REPO_URL and _TOKEN:
    git_wiki_provider: WikiContextProvider | None = WikiContextProvider(
        id="git_wiki",
        backend=GitBackend(
            repo_url=_REPO_URL,
            branch=_BRANCH,
            github_token=_TOKEN,
            local_path=_LOCAL_PATH,
        ),
        web=ParallelMCPBackend(),
        model=sub_agent_model(),
    )
    git_wiki: Agent | None = Agent(
        id="git-wiki",
        name="GitWiki",
        model=default_model(),
        db=get_db(),
        tools=git_wiki_provider.get_tools(),
        instructions=GIT_WIKI_INSTRUCTIONS + "\n\n" + git_wiki_provider.instructions(),
        enable_agentic_memory=True,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )
else:
    git_wiki_provider = None
    git_wiki = None
