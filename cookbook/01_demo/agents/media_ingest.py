"""
MediaIngest Agent (env-gated)
=============================

Turn media into wiki pages. A Gemini 3.5 Flash agent that reads an image,
audio clip, video, or PDF, digests it into clean structured markdown,
fills gaps with cited web research (Parallel MCP), and files the result
into the wiki.

This is the multimodal front door of the knowledge base: drop a whiteboard
photo or a voice memo (in the AgentOS UI or Slack) and it lands as a clean,
linked page. The structured digest is the product — far more useful than
the raw file. Keep originals wherever you like; the wiki holds the
distilled, searchable version.

Files into Notion when NOTION_API_KEY + NOTION_DATABASE_ID are set (see
notion_wiki.py); otherwise into the local markdown wiki. Either way it
reuses the same provider instance as the other wiki agents, so a page it
files is immediately visible to LocalWiki / NotionWiki and the Researcher.

Env-gated: registered only when GOOGLE_API_KEY is set — Gemini's multimodal
understanding is what reads the media.

Required env:
  GOOGLE_API_KEY                       (Gemini 3.5 Flash)

Optional env:
  NOTION_API_KEY + NOTION_DATABASE_ID  (file into Notion instead of local md)
  PARALLEL_API_KEY                     (raises the Parallel MCP rate ceiling)
"""

from os import getenv

from agno.agent import Agent
from db import get_db
from settings import gemini_model

from agents.local_wiki import local_wiki_provider
from agents.notion_wiki import notion_wiki_provider
from agents.web_search import web_provider

# File into Notion when it's configured, else the local markdown wiki. Reuse
# the existing provider instance so writes are shared with the other wiki
# agents (and closed once at AgentOS shutdown — see run.py lifespan).
_wiki_provider = notion_wiki_provider or local_wiki_provider
_wiki_name = "notion" if notion_wiki_provider is not None else "local"


MEDIA_INGEST_INSTRUCTIONS = f"""\
You turn media into wiki pages. When the user shares an image, audio clip,
video, or PDF:

1. Read it carefully. Describe images, transcribe audio, summarize video,
   and extract text and tables from PDFs. Write clean, structured markdown
   — headings, bullets, and any verbatim text worth keeping.
2. Fill the gaps. Call query_web for context, dates, names, or facts the
   media implies but does not state, and cite the URLs you use.
3. File it. Call update_{_wiki_name}_wiki with a clear instruction naming a
   clean kebab-case path and asking the writer to cite sources. The
   structured digest is the product — capture what matters, not the bytes.

Always tell the user where you filed the page.
"""


if getenv("GOOGLE_API_KEY"):
    media_ingest: Agent | None = Agent(
        id="media-ingest",
        name="MediaIngest",
        model=gemini_model(),
        db=get_db(),
        tools=[
            *_wiki_provider.get_tools(),
            *web_provider.get_tools(),
        ],
        instructions=MEDIA_INGEST_INSTRUCTIONS + "\n\n" + _wiki_provider.instructions(),
        enable_agentic_memory=True,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )
else:
    media_ingest = None
