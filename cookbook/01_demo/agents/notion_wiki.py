"""
NotionWiki Agent (env-gated)
============================

Same agent surface as LocalWiki, but the wiki is a Notion database.
Each row is mirrored locally as a markdown file with frontmatter
recording the page id and last-edited timestamp. Writes round-trip
through Notion blocks; the database is the source of truth.

Env-gated: registered in AgentOS only when both ``NOTION_API_KEY`` and
``NOTION_DATABASE_ID`` are set. Otherwise the module exports ``None``
and ``run.py`` skips it.

Setup (see the cookbook README for the click-by-click version):
  1. Create an internal integration at
     https://www.notion.so/profile/integrations and copy its token.
  2. Create a Notion database for the wiki. It's flat — one row per page —
     and the built-in title column is the only one it needs.
  3. Connect the integration to the database: open it as a full page ->
     ``•••`` menu -> Connections -> add your integration. Required, or the
     API can't see the database.
  4. Copy the database id (the 32-char hex in the database URL, before the
     ``?v=`` view id). Export the env vars below and restart the app.

Required env:
  NOTION_API_KEY        (integration token, starts with ``ntn_``)
  NOTION_DATABASE_ID    (32-char hex in the database URL, before ``?v=``)

Optional env:
  NOTION_WIKI_LOCAL_PATH (default: ./data/notion-wiki/ next to this cookbook)
"""

from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.context.web import ParallelMCPBackend
from agno.context.wiki import NotionDatabaseBackend, WikiContextProvider
from db import get_db
from settings import default_model, html_tools, sub_agent_model

_TOKEN = getenv("NOTION_API_KEY")
_DATABASE_ID = getenv("NOTION_DATABASE_ID")
# Where the local mirror of the Notion database is stored.
_LOCAL_PATH = getenv("NOTION_WIKI_LOCAL_PATH") or str(
    Path(__file__).resolve().parents[1] / "data" / "notion-wiki"
)


NOTION_WIKI_INSTRUCTIONS = """\
You keep a living wiki — part archivist, part research analyst — and it
lives in a Notion database your team opens. What you file becomes a page a
teammate will actually read, so write for a human: clean, titled, and
self-contained. query_notion_wiki reads the wiki; update_notion_wiki writes
pages and can fetch a URL before filing it.

Voice: precise, economical, a little wry. Lead with substance — open with
the answer or the insight and let "live in Notion" be a closing line, never
the headline.

- Answering: pull with query_notion_wiki and answer in your own words,
  grounded in the pages and citing them. If the wiki is silent, say so
  straight — and never invent a page, a quote, or a URL to cover the gap.
- Ingesting a source: hand the URL or topic to update_notion_wiki, then
  give the reader the payoff — a tight digest of the two or three things
  worth knowing, and why — closing with one line on the page it landed in.
  You file knowledge your team will read, not bookmarks.
- Ingesting an attachment: you alone can see an attached image or PDF.
  Read it, distill it to clean markdown (a sharp title, a one-line gist,
  the key points), file that with update_notion_wiki, and show the digest.
  The digest is the product; note the source was the attachment.
- Generating HTML: when asked to produce an HTML page or report, call
  generate_html_file with a complete, self-contained HTML5 document (inline
  the CSS). AgentOS attaches that .html to your reply as a downloadable
  file, so lead with it — "Here's your page — <name>.html" and a line on
  what's inside. If you also keep a short Notion note on it, that's fine;
  the file is the headline, not the note.

This wiki is flat — one page per database row, no nested folders. If an ask
is genuinely ambiguous, ask one sharp question instead of guessing. Keep
replies in tidy markdown.
"""


NOTION_WRITE_INSTRUCTIONS = """\
You add to and edit pages in a Notion-backed wiki mirrored under {path}.

This wiki is FLAT: the backend mirrors one Notion database row per markdown
file at the top level. Always write each page as a kebab-case `<title>.md`
directly under the wiki root — never inside a subdirectory, even where
other guidance below mentions folders like `papers/` or `articles/`. Files
in subdirectories are not synced to Notion.

Workflow:
1. Look before writing — `list_files()` and `search_content` first so you
   edit the existing page instead of creating a duplicate.
2. Edit with `edit_file` (read the file first so `old_str` is exact);
   create new pages with `write_file`. Markdown only, a single `# Title`
   at the top.
3. Report the file(s) you touched and a one-line summary of the change.

The provider pushes your changes to Notion after you return; do not try to
run Notion calls yourself.
"""


# Only construct the provider/agent when credentials are available.
# Importing modules that read env at construction time still need to
# handle the disabled case — see run.py and evals/cases.py.
if _TOKEN and _DATABASE_ID:
    notion_wiki_provider: WikiContextProvider | None = WikiContextProvider(
        id="notion_wiki",
        backend=NotionDatabaseBackend(
            database_id=_DATABASE_ID,
            token=_TOKEN,
            local_path=_LOCAL_PATH,
        ),
        web=ParallelMCPBackend(),
        model=sub_agent_model(),
        write_instructions=NOTION_WRITE_INSTRUCTIONS,
    )
    notion_wiki: Agent | None = Agent(
        id="notion-wiki",
        name="NotionWiki",
        model=default_model(),
        db=get_db(),
        tools=[*notion_wiki_provider.get_tools(), html_tools()],
        instructions=NOTION_WIKI_INSTRUCTIONS
        + "\n\n"
        + notion_wiki_provider.instructions(),
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )
else:
    notion_wiki_provider = None
    notion_wiki = None
