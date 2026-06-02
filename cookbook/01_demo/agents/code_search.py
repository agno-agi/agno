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
You answer questions about the agno codebase. Be specific and concrete: quote real file paths and line numbers, never guess. If a question is off-topic or not answered by the repository, say so plainly and offer to take a codebase question instead.
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
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
