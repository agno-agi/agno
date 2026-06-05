"""
NotionWiki Agent (env-gated)
============================

Same agent surface as LocalWiki, but the wiki is a Notion database.
Each row is mirrored locally as a markdown file with frontmatter
recording the page id and last-edited timestamp. Writes round-trip
through Notion blocks; the database is the source of truth.

The point: the wiki the agent reads + edits is the same database your
team already opens in Notion. Agents file structured notes; humans
read and edit them in the UI they already use.

Env-gated: registered in AgentOS only when both ``NOTION_API_KEY`` and
``NOTION_DATABASE_ID`` are set. Otherwise the module exports ``None``
and ``run.py`` skips it.

Required env:
  NOTION_API_KEY        (integration token from Notion -> Settings -> Connections)
  NOTION_DATABASE_ID    (UUID from the database URL)

Optional env:
  NOTION_WIKI_LOCAL_PATH (default: ./data/notion-wiki/ next to this cookbook)
"""

from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.context.web import ParallelMCPBackend
from agno.context.wiki import NotionDatabaseBackend, WikiContextProvider
from db import get_db
from settings import default_model, sub_agent_model

_TOKEN = getenv("NOTION_API_KEY")
_DATABASE_ID = getenv("NOTION_DATABASE_ID")
# Where the local mirror of the Notion database is stored.
_LOCAL_PATH = getenv("NOTION_WIKI_LOCAL_PATH") or str(
    Path(__file__).resolve().parents[1] / "data" / "notion-wiki"
)


NOTION_WIKI_INSTRUCTIONS = """\
You curate a Notion-backed markdown wiki through two tools:
query_notion_wiki (reads the wiki) and update_notion_wiki (adds or edits
pages, and can fetch a URL before writing). Writes round-trip to the
Notion database your team opens, so keep pages clean and self-contained.
What you do:

- Reading: relay what query_notion_wiki returns faithfully. If the wiki
  has no page on the topic, say so plainly — never invent pages,
  content, or URLs.
- Ingesting sources: when asked to add, save, file, or ingest a URL or
  topic, hand it to update_notion_wiki, then report where the page landed.
- Ingesting media: you alone can see an attached image or PDF, so digest
  it yourself into clean markdown — a title, a short summary, the key
  points — then file it with update_notion_wiki and show that digest in
  your reply, noting where it landed. The digest is the product, not the
  raw file; record that the source was the attachment.

This wiki is flat — one page per database row, no nested folders. If an
ask is ambiguous, ask one short question instead of guessing. Keep your
own replies in tidy markdown.
"""


# The write sub-agent's library default (and the appended web-ingest
# stanza) suggest filing pages into folders like ``papers/``. Notion's
# mirror is flat — the backend only syncs ``*.md`` at the wiki root
# (``glob`` is non-recursive), so a page written into a subdirectory
# would never reach Notion. Override the write prompt to keep it flat.
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
        tools=notion_wiki_provider.get_tools(),
        instructions=NOTION_WIKI_INSTRUCTIONS
        + "\n\n"
        + notion_wiki_provider.instructions(),
        enable_agentic_memory=True,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )
else:
    notion_wiki_provider = None
    notion_wiki = None
