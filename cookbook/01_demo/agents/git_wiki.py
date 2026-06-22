"""
GitWiki Agent (env-gated)
=========================

Same as LocalWiki, but the wiki lives in a git repository.
After every write, the backend stages, commits with an LLM-summarised message, rebases onto the remote, and pushes.

Env-gated: registered in AgentOS only when both ``WIKI_REPO_URL`` and ``WIKI_GITHUB_TOKEN`` are set. Otherwise the module exports ``None`` and ``run.py`` skips it.

Setup (see the cookbook README for the click-by-click version):
  1. Pick a GitHub repo for the wiki. A fresh repo with an initial commit
     works — the target branch (``main`` by default) must already exist to
     clone.
  2. Create a token with write access: a fine-grained PAT scoped to that repo
     with Contents: Read and write, or a classic PAT with the ``repo`` scope.
  3. Export the env vars below (HTTPS URL, not SSH) and restart the app.

Required env:
  WIKI_REPO_URL       (https://github.com/<owner>/<repo>.git — HTTPS, not SSH)
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
from settings import default_model, html_tools, sub_agent_model

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
- Generating HTML: when asked to produce an HTML page or report, call
  generate_html_file with a complete HTML5 document (doctype, html, head,
  body). The .html file it returns is the deliverable on its own — do not
  also file it as a wiki page unless asked. Tell the user you generated a
  downloadable HTML file and name it.

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
        tools=[*git_wiki_provider.get_tools(), html_tools()],
        instructions=GIT_WIKI_INSTRUCTIONS + "\n\n" + git_wiki_provider.instructions(),
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )
else:
    git_wiki_provider = None
    git_wiki = None
