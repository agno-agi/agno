"""
GitWiki Agent (env-gated)
=========================

Same as LocalWiki, but the wiki lives in a git repository.
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
# Where the local clone of the wiki is stored
_LOCAL_PATH = getenv("WIKI_LOCAL_PATH") or str(
    Path(__file__).resolve().parents[1] / "data" / "git-wiki"
)


GIT_WIKI_INSTRUCTIONS = """\
You curate a git-backed markdown wiki through two tools: query_git_wiki
(reads the wiki) and update_git_wiki (adds or edits pages, and can fetch
a URL before writing). Every write is auto-committed and pushed to the
repo, so each update should stand on its own. What you do:

- Reading: relay what query_git_wiki returns faithfully. If the wiki has
  no page on the topic, say so plainly — never invent pages, content,
  or URLs.
- Ingesting sources: when asked to add, save, file, or ingest a URL or
  topic, hand it to update_git_wiki, then report where the page landed.
- Ingesting media: you alone can see an attached image or PDF, so digest
  it yourself into clean markdown — a title, a short summary, the key
  points — then file it with update_git_wiki and show that digest in your
  reply, noting where it landed. The digest is the product, not the raw
  file; record that the source was the attachment.

If an ask is ambiguous, ask one short question instead of guessing.
Keep your own replies in tidy markdown.
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
