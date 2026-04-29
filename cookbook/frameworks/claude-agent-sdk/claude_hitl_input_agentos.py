"""
Claude Agent SDK with HITL User Input on AgentOS
==================================================
Serves a Claude agent that pauses for user approval before executing
write tools (Bash, Write, Edit). Users can approve, deny, or modify
tool arguments via the AgentOS UI before execution proceeds.

Requirements:
    pip install claude-agent-sdk

Usage:
    python cookbook/frameworks/claude-agent-sdk/claude_hitl_input_agentos.py

Then open http://localhost:7777 and try:
    "Run 'echo hello' in bash and write the output to greeting.txt"

The agent will pause before each write tool, showing a confirmation
dialog in the UI where you can approve, deny, or edit the arguments.
"""

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.os.app import AgentOS

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = ClaudeAgent(
    name="Claude HITL Input Agent",
    description="A Claude agent that pauses and lets you edit tool arguments before execution",
    model="claude-sonnet-4-20250514",
    allowed_tools=["Bash", "Write", "Read", "Edit"],
    permission_mode="default",
    hitl_mode="user_input",  # Shows editable input fields (not just confirm/deny)
    max_turns=10,
    db=db,
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="claude_hitl_input_agentos:app", reload=True)
