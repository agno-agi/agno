"""
Subagents in AgentOS
=============================

Serves an agent with the SubAgent toolkit through AgentOS. The main agent runs
on GPT-5.6 Terra and delegates independent sub-tasks to subagents running on
GPT-5.6 Luna by calling spawn_agent multiple times in parallel.

Every spawn_agent call runs in its own "<parent id>-subagent-task-<uuid>" session
with user_id set to the main agent's id, so while a request is running you can
open the AgentOS UI and watch each subagent session live.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/subagents_os.py
Then open http://localhost:7777 (config at http://localhost:7777/config).
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.subagents import SubAgent
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/subagents_os.db")

main_agent = Agent(
    name="Research Orchestrator",
    model=OpenAIResponses(id="gpt-5.6-terra"),
    tools=[
        WebSearchTools(),
        SubAgent(model=OpenAIResponses(id="gpt-5.6-luna"), db=db),
    ],
    db=db,
    instructions=(
        "You are a research orchestrator. Split research into independent "
        "sub-topics and spawn one subagent per topic in a single response. Ask "
        "each for a concise summary of findings with sources, then synthesize "
        "and write the answer yourself. Answer follow-up questions and small "
        "clarifications directly with your own tools - only spawn subagents "
        "when there is fresh independent research to parallelize."
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
