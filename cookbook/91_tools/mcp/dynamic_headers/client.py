"""
Dynamic MCP Headers through AgentOS
Forward AgentOS run identity to an MCP server through an MCPTools header
provider. AgentOS owns the MCP connection lifecycle while the app is running.

Prerequisites: OPENAI_API_KEY and the sibling server.py running on port 8000.
Run: .venvs/demo/bin/python cookbook/91_tools/mcp/dynamic_headers/client.py
Try: POST a run with user_id and session_id, then inspect the MCP server log.
"""

from typing import TYPE_CHECKING, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.run import RunContext
from agno.tools.mcp import MCPTools

if TYPE_CHECKING:
    from agno.agent import Agent as AgentType
    from agno.team import Team as TeamType


# ---------------------------------------------------------------------------
# Create MCP Client
# ---------------------------------------------------------------------------


def header_provider(
    run_context: Optional[RunContext] = None,
    agent: Optional["AgentType"] = None,
    team: Optional["TeamType"] = None,
) -> dict[str, str]:
    """Build headers for discovery or for a contextual agent or team run."""
    entity_name = (
        agent.name
        if agent is not None
        else team.name
        if team is not None
        else "unnamed-agno-entity"
    )
    tenant_id = (
        run_context.metadata.get("tenant_id", "no-tenant")
        if run_context is not None and run_context.metadata
        else "no-tenant"
    )
    return {
        "X-User-ID": run_context.user_id
        if run_context is not None and run_context.user_id
        else "anonymous",
        "X-Session-ID": run_context.session_id
        if run_context is not None
        else "unknown",
        "X-Run-ID": run_context.run_id if run_context is not None else "unknown",
        "X-Tenant-ID": str(tenant_id),
        "X-Agent-Name": entity_name,
    }


mcp_tools = MCPTools(
    url="http://localhost:8000/mcp",
    transport="streamable-http",
    header_provider=header_provider,
)

dynamic_headers_agent = Agent(
    id="dynamic-header-agent",
    name="Dynamic Header Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[mcp_tools],
)

agent_os = AgentOS(
    description="AgentOS-managed MCP client with dynamic request headers",
    agents=[dynamic_headers_agent],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
