"""
Reasoning Agent
===============

An agent with ReasoningTools that thinks step-by-step before answering.
Combines structured reasoning with web search for finance questions.

Key concepts:
  - ``ReasoningTools(add_instructions=True)`` injects chain-of-thought
    prompting into the agent's system message.
  - The agent uses tables for data display and keeps thinking concise.

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.reasoning import ReasoningTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/persistent_memory.db")

reasoning_finance_agent = Agent(
    name="Reasoning Finance Agent",
    model=Claude(id="claude-sonnet-4-20250514"),
    db=agent_db,
    tools=[
        ReasoningTools(add_instructions=True),
        WebSearchTools(),
    ],
    instructions="Use tables to display data. When you use thinking tools, keep the thinking brief.",
    add_datetime_to_context=True,
    markdown=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    agents=[reasoning_finance_agent],
    interfaces=[Slack(agent=reasoning_finance_agent)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="reasoning_agent:app", reload=True)
