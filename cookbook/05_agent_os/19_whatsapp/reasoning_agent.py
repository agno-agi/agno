"""
Show Agent Reasoning on WhatsApp
================================

Enable the WhatsApp interface's show_reasoning option. The interface sends
available reasoning content as a separate formatted message before sending the
Agent's final response.

Prerequisites: OPENAI_API_KEY and the four WHATSAPP_* credentials in README.md
Run: .venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/reasoning_agent.py
Try: Ask for a concise comparison of two public companies
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create the Reasoning WhatsApp AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="whatsapp-reasoning-db",
    db_file="tmp/whatsapp_reasoning.db",
)

finance_agent = Agent(
    id="whatsapp-reasoning-agent",
    name="WhatsApp Reasoning Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[
        ReasoningTools(add_instructions=True),
        YFinanceTools(),
    ],
    instructions=[
        "Compare the requested companies using current financial data.",
        "Keep reasoning focused and the final answer concise for WhatsApp.",
    ],
    add_datetime_to_context=True,
)

agent_os = AgentOS(
    id="whatsapp-reasoning-os",
    description="An AgentOS that exposes reasoning through WhatsApp messages.",
    agents=[finance_agent],
    interfaces=[
        Whatsapp(
            agent=finance_agent,
            show_reasoning=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the Reasoning WhatsApp Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
