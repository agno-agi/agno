from datetime import datetime

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools import tool
from agno.tools.exa import ExaTools
from agno.tools.mcp import MCPTools


# ************* Create Tool that requires confirmation. *************
@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email to the user.

    Args:
        to (str): The address to send the email to.
        subject (str): The subject of the email.
        body (str): The body of the email.
    """
    # Implementation here
    return f"Email sent to {to} with subject {subject} and body {body}"


# ************* Create Agent *************
agno_agent = Agent(
    name="Agno Agent",
    model=Claude(id="claude-sonnet-4-5"),
    # Add the Agno MCP server to the Agent
    tools=[
        ExaTools(start_published_date=datetime.now().strftime("%Y-%m-%d")),
        MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp"),
        send_email,
    ],
    instructions="The user's email is {user_id}",
    # Add a database to the Agent
    db=SqliteDb(db_file="tmp/agno.db"),
    add_datetime_to_context=True,
    # Add the previous session history to the context
    add_history_to_context=True,
    # Enable agentic memory
    enable_agentic_memory=True,
    markdown=True,
)

# ************* Create AgentOS *************
agent_os = AgentOS(agents=[agno_agent])
app = agent_os.get_app()

# ************* Run AgentOS *************
if __name__ == "__main__":
    agent_os.serve(app="02_agno_agentos:app", reload=True)
