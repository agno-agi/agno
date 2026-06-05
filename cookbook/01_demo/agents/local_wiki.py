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
from settings import gemini_flash

WIKI_PATH = Path(__file__).resolve().parents[1] / "data" / "wiki"
WIKI_PATH.mkdir(parents=True, exist_ok=True)
if not (WIKI_PATH / "README.md").exists():
    (WIKI_PATH / "README.md").write_text(
        "# Local Wiki\n\n"
        "Pages live under `papers/`, `articles/`, and the root.\n"
        "Ask the agent to ingest a URL and it will file the digest here.\n"
    )

local_wiki_provider = WikiContextProvider(
    id="local_wiki",
    backend=FileSystemBackend(path=WIKI_PATH),
    web=ParallelMCPBackend(),
    model=gemini_flash(),
)


LOCAL_WIKI_INSTRUCTIONS = """\
You curate a local markdown wiki. Three things you do:

1. Answer "what does the wiki say about X" — call query_local_wiki
   and quote the page. If the wiki is silent, say so plainly rather
   than guessing.
2. Ingest sources — when asked to "add", "save", "file", or "ingest"
   a URL or topic, call update_local_wiki with a clear instruction
   that names the destination path and asks the writer to cite sources.
3. Ingest media — if the user attaches an image, audio clip, video, or
   PDF, read it yourself (describe images, transcribe audio, summarize
   video, extract text from PDFs) into clean structured markdown, then
   call update_local_wiki to file it. The digest is the product —
   capture what matters, not the raw file.
"""


local_wiki = Agent(
    id="local-wiki",
    name="LocalWiki",
    model=gemini_flash(),
    db=get_db(),
    tools=local_wiki_provider.get_tools(),
    instructions=LOCAL_WIKI_INSTRUCTIONS + "\n\n" + local_wiki_provider.instructions(),
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
