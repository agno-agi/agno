"""
Coding Agent with Subagents in AgentOS
=============================

Serves a coding orchestrator through AgentOS. The main agent runs on GPT-5.6
Terra, plans the project, then delegates research, frontend, backend, database
and scripts work to GPT-5.6 Luna subagents that build the project in parallel
inside a shared workspace.

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
from agno.models.openai import OpenAIResponses
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
        SubAgent(model=OpenAIResponses(id="gpt-5.6-luna")),
    ],
    db=db,
    instructions=(
        "You are a coding orchestrator. Subagents do the build work; you plan, "
        "delegate, review and answer the user.\n"
        "How subagents work:\n"
        "- spawn_agent(task) runs one task on a subagent and returns its result. "
        "Subagents have the same tools as you, but they do not see this conversation, "
        "so every brief must be self-contained: project folder path, the files that "
        "subagent owns, exactly what to build or research, and what to report back "
        "(files created plus a short summary - never full file contents).\n"
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
        "- Finish with a summary of the project structure and how to run it."
    ),
    markdown=True,debug_mode=True,
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
