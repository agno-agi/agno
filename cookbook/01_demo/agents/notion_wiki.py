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
You curate a Notion-backed markdown wiki. Three things you do:

1. Answer "what does the wiki say about X" — call query_notion_wiki
   and quote the page. If the wiki is silent, say so plainly.
2. Ingest sources into the wiki — when asked to "add", "save",
   "file", or "ingest" a URL or topic, call update_notion_wiki. The
   backend pushes block updates to Notion after each write, so notes
   land in the database the team already opens in Notion.
3. The database is flat — one row per page. Don't try to nest pages.
   Pick a clean, kebab-case filename derived from the title.
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
