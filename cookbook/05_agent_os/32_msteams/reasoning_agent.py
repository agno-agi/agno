"""
Show Agent Reasoning on Microsoft Teams
========================================

Send available reasoning as a separate message before the final response.
Prerequisites: OPENAI_API_KEY and the MICROSOFT_APP_* credentials in README.md
Run: python cookbook/05_agent_os/32_msteams/reasoning_agent.py
Try: Ask for a comparison of two approaches to reducing API latency.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.msteams import MSTeams
from agno.tools.reasoning import ReasoningTools

reasoning_agent = Agent(
    id="msteams-reasoning-agent",
    name="Teams Reasoning Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(id="msteams-reasoning-db", db_file="tmp/msteams_reasoning.db"),
    tools=[ReasoningTools(add_instructions=True)],
    add_history_to_context=True,
    instructions="Compare the alternatives carefully. Keep reasoning focused and the final answer concise.",
)
agent_os = AgentOS(
    id="msteams-reasoning-os",
    agents=[reasoning_agent],
    interfaces=[MSTeams(agent=reasoning_agent, show_reasoning=True)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app)
