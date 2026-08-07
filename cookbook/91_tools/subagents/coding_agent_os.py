"""
Coding Agent with Subagents in AgentOS
=============================

Serves a coding orchestrator through AgentOS. The main agent runs on GPT-5.6
Terra, plans the project, then delegates research, frontend, backend, database
and scripts work to GPT-5.6 Luna subagents that build the project in parallel
inside a shared workspace.

This example restricts what subagents may use: SubagentsManager(tools=[...])
declares an explicit allowed set (websearch, website reading and the coding
surface). The orchestrator keeps FileGenerationTools and the Workspace
move/delete surface to itself - subagents build code, the orchestrator manages
the workspace and produces downloadable artifacts. Within the allowed set, the
model can restrict each spawn further by name (a pure research spawn only
needs websearch).

Projects are created under the tmp/projects directory next to this file.
Subagent activity streams live into the parent's chat as nested sub-agent
runs; nothing about them is persisted.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/coding_agent_os.py
Then open http://localhost:7777 (config at http://localhost:7777/config).
"""

from pathlib import Path

from agno.agent import Agent, SubagentsManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.coding import CodingTools
from agno.tools.file_generation import FileGenerationTools
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
    model=OpenAIResponses(id="gpt-5.6-terra"),
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
    ],
    subagents=SubagentsManager(
        models={
            "fast": (
                OpenAIResponses(id="gpt-5.6-luna"),
                "scaffolding, boilerplate and lookups",
            ),
            "deep": (
                OpenAIResponses(id="gpt-5.6-terra"),
                "tricky logic and architecture",
            ),
        },
        # Subagents get the build and research surface only - artifact generation
        # and workspace move/delete stay with the orchestrator
        tools=[
            WebSearchTools(),
            WebsiteTools(),
            CodingTools(base_dir=PROJECTS_DIR, all=True),
        ],
    ),
    db=db,
    instructions=(
        "You are a coding orchestrator. Subagents do the build work; you plan, "
        "delegate, review and answer the user.\n"
        "How subagents work:\n"
        "- spawn_agent(task) runs one task on a subagent and returns its result. "
        "Subagents can search, read websites and write code, but they do not see "
        "this conversation, so every brief must be self-contained: project folder "
        "path, the files that subagent owns, exactly what to build or research, and "
        "what to report back (files created plus a short summary - never full file "
        "contents).\n"
        "- Pick the model per task (fast for scaffolding and lookups, deep for tricky "
        "logic) and pass a tools subset when a spawn only needs part of the allowed "
        "set (a research spawn only needs websearch).\n"
        "- spawn_agent calls made in the same response run in parallel, so total time "
        "equals the largest brief, not the sum.\n"
        "How to use them:\n"
        "- Spawn subagents only for real build or research work. Answer questions, "
        "small follow-ups and one-file tweaks yourself with your own tools - "
        "spawning costs more than doing it.\n"
        "- Plan in your head (never in a file) and tell the user the plan.\n"
        "- Split the work into small independent tasks: at most 2-3 closely related "
        "items per brief, and never give two subagents the same files.\n"
        "- Tasks in the same wave must not depend on each other. If one task's output "
        "feeds another (e.g. researching a framework's docs while another subagent "
        "builds with that framework), run the research wave first and put its "
        "findings into the build brief of the next wave.\n"
        "- Delegate a wave of spawn_agent calls in one response, review the results, "
        "re-plan, then delegate the next wave. Repeat until done; testing and "
        "verification are subagent tasks too.\n"
        "- Workspace cleanup and downloadable artifacts (PDF, DOCX, CSV) are yours "
        "alone - subagents cannot generate artifacts or move and delete files.\n"
        "- Finish with a summary of the project structure and how to run it."
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
    agent_os.serve(app="coding_agent_os:app")
