"""
Google Workspace Agent — Full Suite
====================================

Same as workspace_agent.py but with all major Workspace services enabled:
Gmail, Drive, Calendar, Sheets, Docs, and Chat.

Note: More services = more tools exposed. Some MCP clients have tool limits
(typically 50-100). Use the selective version (workspace_agent.py) if you
hit tool count limits.

Prerequisites:
    1. Install gws CLI:
        npm install -g @googleworkspace/cli

    2. Authenticate:
        gws auth setup

    3. Set environment variables:
        export OPENAI_API_KEY=your-openai-api-key

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_full.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/workspace_full.db")

# Expose all major Workspace services via MCP
workspace_tools = MCPTools(
    command="gws",
    args=["mcp", "-s", "gmail,drive,calendar,sheets,docs,chat"],
)

workspace_agent = Agent(
    id="workspace-full-agent",
    name="Workspace Assistant",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[workspace_tools],
    instructions=[
        "You are a full-featured Google Workspace assistant.",
        "You can manage emails (Gmail), files (Drive), events (Calendar), "
        "spreadsheets (Sheets), documents (Docs), and messages (Chat).",
        "When asked to create a spreadsheet, use Sheets tools.",
        "When asked to draft a document, use Docs tools.",
        "When asked to send a chat message, use Chat tools.",
        "For multi-step tasks, plan your approach and execute step by step.",
        "Always confirm before sending emails, creating events, or modifying documents.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    description="Full Google Workspace assistant via gws MCP",
    agents=[workspace_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="workspace_full:app", reload=True)
