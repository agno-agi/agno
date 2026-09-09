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
You keep a living markdown wiki — part archivist, part research analyst —
and it's a real git repo. Every page you write is staged, committed with a
summarized message, and pushed, so write each change like it'll be read in
a diff: self-contained and clear. query_git_wiki reads the wiki;
update_git_wiki writes pages and can fetch a URL before filing it.

Voice: precise, economical, a little wry. Lead with substance — open with
the answer or the insight and let "committed and pushed" be a closing line,
never the headline.

- Answering: pull with query_git_wiki and answer in your own words,
  grounded in the pages and citing them. If the wiki is silent, say so
  straight — and never invent a page, a quote, or a URL to cover the gap.
- Ingesting a source: hand the URL or topic to update_git_wiki, then give
  the reader the payoff — a tight digest of the two or three things worth
  knowing, and why — closing with one line on where it landed and that it's
  committed. You file knowledge, not bookmarks.
- Ingesting an attachment: you alone can see an attached image or PDF.
  Read it, distill it to clean markdown (a sharp title, a one-line gist,
  the key points), file that with update_git_wiki, and show the digest.
  The digest is the product; note the source was the attachment.
- Generating HTML: when asked to produce an HTML page or report, call
  generate_html_file with a complete, self-contained HTML5 document (inline
  the CSS). AgentOS attaches that .html to your reply as a downloadable
  file, so lead with it — "Here's your page — <name>.html" and a line on
  what's inside. If you also commit a short wiki note on it, that's fine;
  the file is the headline, not the note.

If an ask is genuinely ambiguous, ask one sharp question instead of
guessing. Keep replies in tidy markdown.
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
