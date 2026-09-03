"""
CodeSearch Agent
================

Answers questions about the agno repository.

Uses ``WorkspaceContextProvider``, which exposes a read-only ``Workspace`` toolkit (list / search / read) behind a sub-agent.

The parent agent sees a single ``query_codebase(question)`` tool.
"""

from pathlib import Path

from agno.agent import Agent
from agno.context.workspace import WorkspaceContextProvider
from db import get_db
from settings import default_model, sub_agent_model

REPO_ROOT = Path(__file__).resolve().parents[3]

code_search_provider = WorkspaceContextProvider(
    id="codebase",
    name="Agno Repo",
    root=REPO_ROOT,
    model=sub_agent_model(),
)


CODE_SEARCH_INSTRUCTIONS = """\
You're a senior engineer who knows the agno codebase cold, and you answer
questions about it by actually reading the source with query_codebase —
never from memory. Ground every claim in what's there: cite real file
paths with line numbers, and quote the code instead of paraphrasing it.

Voice: direct and precise, the way a good staff engineer answers in a
review — no hedging, no filler.

If the codebase doesn't have it — a function that isn't defined, a file
that doesn't exist — say so flatly rather than bluffing a plausible answer.
For questions outside this repo, say it's not a code question about agno
and offer to dig into one. Keep answers in tidy markdown.
"""


code_search = Agent(
    id="code-search",
    name="CodeSearch",
    model=default_model(),
    db=get_db(),
    tools=code_search_provider.get_tools(),
    instructions=CODE_SEARCH_INSTRUCTIONS
    + "\n\n"
    + code_search_provider.instructions(),
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
