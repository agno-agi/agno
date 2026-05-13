"""
Web Search Agent
================

Web research via Parallel's public MCP endpoint. Keyless by default (rate-limited); set ``PARALLEL_API_KEY`` to raise the ceiling.

The agent sees a single ``query_web(question)`` tool that hands off to a sub-agent with ``web_search`` + ``web_fetch``. The sub-agent does the search/fetch loop and returns a synthesized answer; the parent agent stays focused on the user's question.
"""

from agno.agent import Agent
from agno.context.web import ParallelMCPBackend, WebContextProvider
from db import get_db
from settings import default_model, sub_agent_model

web_provider = WebContextProvider(
    id="web",
    backend=ParallelMCPBackend(),
    model=sub_agent_model(),
)


WEB_SEARCH_INSTRUCTIONS = """\
You answer questions using current information from the web.

For any non-trivial factual claim, call query_web and cite the URLs
you used as plain links. Prefer recent, authoritative sources. If
the search returns nothing useful, say so plainly rather than
guessing.
"""


web_search = Agent(
    id="web-search",
    name="WebSearch",
    model=default_model(),
    db=get_db(),
    tools=web_provider.get_tools(),
    instructions=WEB_SEARCH_INSTRUCTIONS + "\n\n" + web_provider.instructions(),
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
