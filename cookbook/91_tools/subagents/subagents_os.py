"""
Subagents in AgentOS
=============================

Serves an agent with subagents enabled through AgentOS. The main agent runs on
GPT-5.6 Terra and delegates independent sub-tasks by calling spawn_agent
multiple times in parallel, picking a model option per task: "fast" (GPT-5.6
Luna) for lookups and "deep" (GPT-5.6 Terra) for hard research.

Subagents run in-process inside the parent's run and session. Their activity
streams live into the parent's chat as nested sub-agent runs (tagged with
parent_run_id), and each tool result is the subagent's answer. Subagent runs
are ephemeral - nothing about them is persisted.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/subagents_os.py
Then open http://localhost:7777 (config at http://localhost:7777/config).
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.subagent import SubagentsConfig
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/subagents_os.db")

main_agent = Agent(
    name="Research Orchestrator",
    model=OpenAIResponses(id="gpt-5.6-terra"),
    tools=[WebSearchTools()],
    subagents_config=SubagentsConfig(
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
    instructions=(
        "You are a research orchestrator. Split research into independent "
        "sub-topics and spawn one subagent per topic in a single response. "
        "Ask each for a concise summary of findings with sources, then "
        "synthesize and write the answer yourself. Answer follow-up "
        "questions and small clarifications directly with your own tools - "
        "only spawn subagents when there is fresh independent research to "
        "parallelize."
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
