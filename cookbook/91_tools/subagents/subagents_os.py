"""
Subagents in AgentOS
=============================

Serves an agent with the SubAgent toolkit through AgentOS. The main agent runs
on Claude Sonnet 5 and delegates independent sub-tasks to subagents running on
Claude Haiku by calling run_task multiple times in parallel.

Every run_task call runs in its own "<parent id>-subagent-task-<uuid>" session
with user_id set to the main agent's id, so while a request is running you can
open the AgentOS UI and watch each subagent session live.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/subagents_os.py
Then open http://localhost:7777 (config at http://localhost:7777/config).
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.subagents import SubAgent
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/subagents_os.db")

main_agent = Agent(
    name="Sonnet Orchestrator",
    model=Claude(id="claude-sonnet-5"),
    tools=[
        WebSearchTools(),
        SubAgent(model=Claude(id="claude-haiku-4-5"), db=db),
    ],
    db=db,
    instructions=(
        "You are a research orchestrator. Delegate independent research "
        "sub-tasks to subagents and focus on synthesis and writing."
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(agents=[main_agent], db=db)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="subagents_os:app", reload=True)
