"""Router for MCP interface providing Model Context Protocol endpoints."""

import logging
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.http import (
    StarletteWithLifespan,
)

from agno.os.schema import (
    AgentSummaryResponse,
    ConfigResponse,
    InterfaceResponse,
    TeamSummaryResponse,
    WorkflowSummaryResponse,
)

if TYPE_CHECKING:
    from agno.os.app import AgentOS

logger = logging.getLogger(__name__)


def get_mcp_server(
    os: "AgentOS",
) -> StarletteWithLifespan:
    """Attach MCP routes to the provided router."""

    # Create an MCP server
    mcp = FastMCP(os.name or "AgentOS")

    @mcp.tool(name="get_agentos_config", description="Get the configuration of the AgentOS", tags=["core"])  # type: ignore
    async def config() -> ConfigResponse:
        return ConfigResponse(
            os_id=os.os_id or "AgentOS",
            description=os.description,
            available_models=os.config.available_models if os.config else [],
            databases=[db.id for db in os.dbs.values()],
            chat=os.config.chat if os.config else None,
            session=os._get_session_config(),
            memory=os._get_memory_config(),
            knowledge=os._get_knowledge_config(),
            evals=os._get_evals_config(),
            metrics=os._get_metrics_config(),
            agents=[AgentSummaryResponse.from_agent(agent) for agent in os.agents] if os.agents else [],
            teams=[TeamSummaryResponse.from_team(team) for team in os.teams] if os.teams else [],
            workflows=[WorkflowSummaryResponse.from_workflow(w) for w in os.workflows] if os.workflows else [],
            interfaces=[
                InterfaceResponse(type=interface.type, version=interface.version, route=interface.router_prefix)
                for interface in os.interfaces
            ],
        )

    mcp_app = mcp.http_app(path="/mcp")
    return mcp_app
