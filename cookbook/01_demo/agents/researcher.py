"""
Researcher Agent
================

Composes three context providers on one agent:

  query_web            — keyless web research via Parallel MCP
  query_local_wiki     — existing knowledge in the local wiki
  update_local_wiki    — file new findings back to the wiki
  query_codebase       — repository context when relevant

Same provider *instances* as the standalone LocalWiki, WebSearch, and
CodeSearch agents — so anything the Researcher writes to the wiki is
immediately visible to LocalWiki, and vice versa.
"""

from agno.agent import Agent
from db import get_db
from settings import default_model

from agents.code_search import code_search_provider
from agents.local_wiki import local_wiki_provider
from agents.web_search import web_provider

RESEARCHER_INSTRUCTIONS = """\
You research topics and synthesize findings. Use the right tool for
the question:

- Wiki first: call query_local_wiki to check what's already known.
  If the wiki has a page, lead with it.
- Web for current or external info: call query_web. Cite the URLs
  you used.
- Codebase for repo-specific questions: call query_codebase. Quote
  file paths and line numbers.
- File findings back: when asked to "save", "file", or "write up"
  a topic, call update_local_wiki with a clear instruction naming
  the destination path and asking the writer to cite sources.

When a question spans multiple sources, run queries in parallel
where possible. Synthesize — don't dump raw tool output.
"""


researcher = Agent(
    id="researcher",
    name="Researcher",
    model=default_model(),
    db=get_db(),
    tools=[
        *web_provider.get_tools(),
        *local_wiki_provider.get_tools(),
        *code_search_provider.get_tools(),
    ],
    instructions=RESEARCHER_INSTRUCTIONS,
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
