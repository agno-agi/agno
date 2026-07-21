"""
Coding Agent with Subagents in AgentOS
=============================

Serves a coding orchestrator through AgentOS. The main agent runs on Claude
Sonnet 5, plans the project, researches docs with web search and page fetching,
then delegates frontend, backend, database and scripts work to Claude Haiku
subagents that build the project in parallel inside a shared workspace.

Projects are created under the tmp/projects directory next to this file. The
subagents inherit every tool except SubAgent itself, so they can research and
write code too. Each subagent run streams live in the AgentOS UI as its own
"<parent id>-subagent-task-<uuid>" session.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/coding_agent_os.py
Then open http://localhost:7777 (config at http://localhost:7777/config).
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.coding import CodingTools
from agno.tools.file_generation import FileGenerationTools
from agno.tools.subagents import SubAgent
from agno.tools.websearch import WebSearchTools
from agno.tools.website import WebsiteTools
from agno.tools.workspace import Workspace

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

PROJECTS_DIR = Path(__file__).parent / "tmp" / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

db = SqliteDb(db_file="tmp/coding_agent_os.db")

coding_agent = Agent(
    name="Coding Orchestrator",
    model=Claude(id="claude-sonnet-5"),
    tools=[
        WebSearchTools(),
        WebsiteTools(),
        # Core coding surface: read_file, edit_file, write_file, run_shell, grep, find, ls
        CodingTools(base_dir=PROJECTS_DIR, all=True),
        # Complementary workspace surface: list_files, search_content, move_file, delete_file
        # (read/write/edit/shell stay with CodingTools so tool names do not collide)
        Workspace(root=PROJECTS_DIR, allowed=["list", "search", "move", "delete"]),
        # Generate downloadable artifacts (PDF, DOCX, CSV, JSON, HTML) into the workspace
        FileGenerationTools(output_directory=str(PROJECTS_DIR), save_files=True),
        SubAgent(model=Claude(id="claude-haiku-4-5")),
    ],
    db=db,
    instructions=(
        "You are a coding orchestrator that builds complete projects.\n"
        "Workflow for a project request:\n"
        "1. Create a new folder for the project (kebab-case name) and write a short "
        "PLAN.md into it describing the architecture and the split of work.\n"
        "2. Research anything unfamiliar first: use web search to find relevant docs "
        "and read_url to fetch the pages you need.\n"
        "3. Delegate independent parts to subagents IN PARALLEL: one subagent each for "
        "frontend, backend, database and scripts, plus one for doc research when useful. "
        "Give every subagent the exact project folder path, the file names it owns, and "
        "a complete self-contained brief. Make sure no two subagents own the same files.\n"
        "4. While subagents work on their parts, write the integration pieces yourself.\n"
        "5. When all subagents are done, review their output with read_file, wire the "
        "pieces together, and verify what you can with run_shell.\n"
        "6. Finish with a summary of the project structure and how to run it."
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(agents=[coding_agent])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="coding_agent_os:app", reload=True)
