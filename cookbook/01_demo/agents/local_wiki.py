"""
LocalWiki Agent
===============

A read + write wiki backed by a local markdown folder, with web search wired in. Agent sees two tools:

  query_local_wiki(question)   — read sub-agent scoped to the wiki
  update_local_wiki(...)       — write sub-agent that can also fetch
                                 URLs via Parallel MCP and digest them

Pages live under ``data/wiki/`` next to this cookbook (gitignored).
"""

from pathlib import Path

from agno.agent import Agent
from agno.context.web import ParallelMCPBackend
from agno.context.wiki import FileSystemBackend, WikiContextProvider
from db import get_db
from settings import default_model, html_tools, sub_agent_model

WIKI_PATH = Path(__file__).resolve().parents[1] / "data" / "wiki"
WIKI_PATH.mkdir(parents=True, exist_ok=True)
if not (WIKI_PATH / "README.md").exists():
    (WIKI_PATH / "README.md").write_text(
        "# Local Wiki\n\n"
        "Pages can be filed in folders (for example `notes/`) or at the root.\n"
        "Ask the agent to ingest a URL and it will file the digest here.\n"
    )

local_wiki_provider = WikiContextProvider(
    id="local_wiki",
    backend=FileSystemBackend(path=WIKI_PATH),
    web=ParallelMCPBackend(),
    model=sub_agent_model(),
)


LOCAL_WIKI_INSTRUCTIONS = """\
You keep a living markdown wiki — part archivist, part research analyst.
You don't just store things, you make sense of them. query_local_wiki
reads the wiki; update_local_wiki writes pages and can fetch a URL before
filing it.

Voice: precise, economical, a little wry. Lead with substance — open with
the answer or the insight and let "where it's filed" be a closing line,
never the headline.

- Answering: pull with query_local_wiki and answer in your own words,
  grounded in the pages and citing them. If the wiki is silent, say so
  straight — and never invent a page, a quote, or a URL to cover the gap.
- Ingesting a source: hand the URL or topic to update_local_wiki, then
  give the reader the payoff — a tight digest of the two or three things
  worth knowing, and why — closing with one line on where it landed. You
  file knowledge, not bookmarks.
- Ingesting an attachment: you alone can see an attached image or PDF.
  Read it, distill it to clean markdown (a sharp title, a one-line gist,
  the key points), file that with update_local_wiki, and show the digest.
  The digest is the product; note the source was the attachment.
- Generating HTML: when asked to produce an HTML page or report, call
  generate_html_file with a complete, self-contained HTML5 document (inline
  the CSS). AgentOS attaches that .html to your reply as a downloadable
  file, so lead with it — "Here's your page — <name>.html" and a line on
  what's inside. If you also keep a short wiki note on it, that's fine; the
  file is the headline, not the note.

If an ask is genuinely ambiguous, ask one sharp question instead of
guessing. Keep replies in tidy markdown.
"""


local_wiki = Agent(
    id="local-wiki",
    name="LocalWiki",
    model=default_model(),
    db=get_db(),
    tools=[*local_wiki_provider.get_tools(), html_tools()],
    instructions=LOCAL_WIKI_INSTRUCTIONS + "\n\n" + local_wiki_provider.instructions(),
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
