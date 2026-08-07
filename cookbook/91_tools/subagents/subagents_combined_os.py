"""
Subagents Combined in AgentOS
=============================

Serves every subagent configuration style side by side in one AgentOS app:

- Researcher: subagents=True - the default manager, subagents inherit
  the agent's model and tools.
- Luna Researcher: a single Model - the orchestrator thinks on GPT-5.6 Terra,
  every subagent runs on GPT-5.6 Luna.
- Research Orchestrator: named model options - the model picks "fast" (Luna)
  or "deep" (Terra) per task.
- Coding Orchestrator: an explicit allowed toolset - subagents get websearch,
  website reading and the coding surface, while artifact generation and
  workspace move/delete stay with the orchestrator.

Subagents run in-process inside the parent's run and session: their activity
streams live into the parent's chat as nested sub-agent runs (tagged with
parent_run_id) and nothing about them is persisted.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/subagents_combined_os.py
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

PROJECTS_DIR = Path(__file__).parent / "tmp" / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

db = SqliteDb(db_file="tmp/subagents_combined_os.db")

RESEARCH_INSTRUCTIONS = (
    "You are a research orchestrator. Split research into independent "
    "sub-topics and spawn one subagent per topic in a single response. Ask "
    "each for a concise summary of findings with sources, then synthesize "
    "and write the answer yourself. Answer follow-up questions and small "
    "clarifications directly with your own tools - only spawn subagents "
    "when there is fresh independent research to parallelize."
)

# ---------------------------------------------------------------------------
# Defaults: subagents=True, subagents inherit model and tools
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[WebSearchTools()],
    subagents=True,
    db=db,
    instructions=RESEARCH_INSTRUCTIONS,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Single model: every subagent runs on GPT-5.6 Luna
# ---------------------------------------------------------------------------

luna_researcher = Agent(
    name="Luna Researcher",
    model=OpenAIResponses(id="gpt-5.6-terra"),
    tools=[WebSearchTools()],
    subagents=SubagentsManager(model=OpenAIResponses(id="gpt-5.6-luna")),
    db=db,
    instructions=RESEARCH_INSTRUCTIONS,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Named model options: the model picks "fast" or "deep" per task
# ---------------------------------------------------------------------------

research_orchestrator = Agent(
    name="Research Orchestrator",
    model=OpenAIResponses(id="gpt-5.6-terra"),
    tools=[WebSearchTools()],
    subagents=SubagentsManager(
        models={
            "fast": (
                OpenAIResponses(id="gpt-5.6-luna"),
                "quick lookups and simple summaries",
            ),
            "deep": (
                OpenAIResponses(id="gpt-5.6-terra"),
                "complex analysis and synthesis",
            ),
        }
    ),
    db=db,
    instructions=RESEARCH_INSTRUCTIONS,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Allowed tools: subagents build and research, the orchestrator keeps
# artifact generation and workspace move/delete to itself
# ---------------------------------------------------------------------------

coding_orchestrator = Agent(
    name="Coding Orchestrator",
    model=OpenAIResponses(id="gpt-5.6-terra"),
    tools=[
        WebSearchTools(),
        WebsiteTools(),
        CodingTools(base_dir=PROJECTS_DIR, all=True),
        Workspace(root=PROJECTS_DIR, allowed=["list", "search", "move", "delete"]),
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
        tools=[
            WebSearchTools(),
            WebsiteTools(),
            CodingTools(base_dir=PROJECTS_DIR, all=True),
        ],
    ),
    db=db,
    instructions=(
        "You are a coding orchestrator. Subagents do the build work; you plan, "
        "delegate, review and answer the user. Every brief must be self-contained: "
        "project folder path, the files that subagent owns, exactly what to build, "
        "and what to report back. Delegate independent tasks as parallel spawn_agent "
        "calls in one response, review, then delegate the next wave. Artifacts and "
        "workspace cleanup are yours alone."
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[researcher, luna_researcher, research_orchestrator, coding_orchestrator],
    db=db,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="subagents_combined_os:app")
