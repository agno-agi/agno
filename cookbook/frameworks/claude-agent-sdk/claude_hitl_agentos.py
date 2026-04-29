"""
Claude Agent SDK with Human-in-the-Loop on AgentOS
====================================================
Demonstrates HITL tool permission approval via AgentOS UI.

When hitl=True and permission_mode="default", the agent pauses before
executing tools and waits for user approval via the AgentOS UI.
The user sees a confirmation dialog and can approve or reject each
tool call.

Requirements:
    pip install claude-agent-sdk

Usage:
    python cookbook/frameworks/claude-agent-sdk/claude_hitl_agentos.py

Then open http://localhost:7777 and send a message like:
    "Search the web for latest AI news"

The agent will pause before using WebSearch and show a confirmation
dialog in the UI. Approve it to let the agent proceed.
"""

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.os.app import AgentOS

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = ClaudeAgent(
    name="Claude HITL Agent",
    description="A Claude agent that asks for permission before using tools",
    model="claude-sonnet-4-20250514",
    allowed_tools=["WebSearch", "Bash", "Read"],
    permission_mode="default",  # HITL: pauses for user approval before tool execution
    max_turns=10,
    db=db,
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="claude_hitl_agentos:app", reload=True)
