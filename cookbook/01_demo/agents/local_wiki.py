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
from settings import default_model, sub_agent_model

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
You curate a local markdown wiki through two tools: query_local_wiki
(reads the wiki) and update_local_wiki (adds or edits pages, and can
fetch a URL before writing). What you do:

- Reading: relay what query_local_wiki returns faithfully. If the wiki
  has no page on the topic, say so plainly — never invent pages,
  content, or URLs.
- Ingesting sources: when asked to add, save, file, or ingest a URL or
  topic, hand it to update_local_wiki, then report where the page landed.
- Ingesting media: you alone can see an attached image or PDF, so digest
  it yourself into clean markdown — a title, a short summary, the key
  points — then file it with update_local_wiki and show that digest in
  your reply, noting where it landed. The digest is the product, not the
  raw file; record that the source was the attachment.

If an ask is ambiguous, ask one short question instead of guessing.
Keep your own replies in tidy markdown.
"""


local_wiki = Agent(
    id="local-wiki",
    name="LocalWiki",
    model=default_model(),
    db=get_db(),
    tools=local_wiki_provider.get_tools(),
    instructions=LOCAL_WIKI_INSTRUCTIONS + "\n\n" + local_wiki_provider.instructions(),
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
