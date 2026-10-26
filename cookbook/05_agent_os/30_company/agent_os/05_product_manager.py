"""
Chat with Product Manager in AgentOS
====================================

Serve the setup from ../05_product_manager.py and chat with Product Manager
for real. An intake reader is registered so chat can create intake Routines.

Prerequisites: OPENAI_API_KEY.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/05_product_manager.py
Try: Ask Product Manager: "Set up a Product for our docs site at
     https://docs.agno.com with an intake Routine run by intake-reader."
     Then: "Propose a Release project with a task to draft release notes."
     The MCP server at http://localhost:7777/mcp exposes the same tools.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, MCPConfig
from agno.registry import Registry
from agno.tools.company import CompanyTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(id="company-product-manager-db", db_file="tmp/company_pm.db")
model = OpenAIResponses(id="gpt-5.6-luna")
tools = CompanyTools(db, user_isolation=True)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

intake_reader = Agent(
    id="intake-reader",
    name="Intake Reader",
    model=model,
    db=db,
    tools=[tools],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-product-manager",
    description="Product Manager plans Company work from chat and MCP.",
    db=db,
    registry=Registry(models=[model], agents=[intake_reader]),
    company=CompanyConfig(),
    user_isolation=True,
    mcp=MCPConfig(tools=[tools]),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
