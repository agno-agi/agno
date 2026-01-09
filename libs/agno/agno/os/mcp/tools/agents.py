"""Agent MCP tools for listing, getting, and managing agent runs."""

from typing import TYPE_CHECKING, List, Optional

from fastmcp import Context, FastMCP

from agno.agent.remote import RemoteAgent
from agno.os.mcp.auth import (
    filter_agents_by_access,
    get_user_id_from_context,
    is_authorization_enabled,
    require_resource_access,
)
from agno.os.routers.agents.schema import AgentResponse
from agno.os.utils import get_agent_by_id

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_agent_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register agent management MCP tools."""

    @mcp.tool(
        name="list_agents",
        description="Get a list of all agents configured in this OS instance",
        tags={"agents"},
    )  # type: ignore
    async def list_agents(ctx: Context) -> List[dict]:
        if os.agents is None:
            return []

        # Filter agents based on user's scopes
        accessible_agents = filter_agents_by_access(ctx, os.agents)

        # Check if user has any access at all
        if is_authorization_enabled(ctx) and not accessible_agents:
            raise Exception("Insufficient permissions to access agents")

        agents = []
        for agent in accessible_agents:
            if isinstance(agent, RemoteAgent):
                agent_response = await agent.get_agent_config()
            else:
                agent_response = await AgentResponse.from_agent(agent=agent)
            agents.append(agent_response.model_dump(exclude_none=True))

        return agents

    @mcp.tool(
        name="get_agent",
        description="Get detailed configuration and capabilities of a specific agent by ID",
        tags={"agents"},
    )  # type: ignore
    async def get_agent(ctx: Context, agent_id: str) -> dict:
        # Check access permission
        require_resource_access(ctx, agent_id, "agents")

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")

        if isinstance(agent, RemoteAgent):
            agent_response = await agent.get_agent_config()
        else:
            agent_response = await AgentResponse.from_agent(agent)
        return agent_response.model_dump(exclude_none=True)

    @mcp.tool(
        name="cancel_agent_run",
        description="Cancel a currently executing agent run",
        tags={"agents"},
    )  # type: ignore
    async def cancel_agent_run(ctx: Context, agent_id: str, run_id: str) -> dict:
        # Check access permission
        require_resource_access(ctx, agent_id, "agents")

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")

        # RemoteAgent.cancel_run is async, Agent.cancel_run is sync
        if isinstance(agent, RemoteAgent):
            cancelled = await agent.cancel_run(run_id=run_id)
        else:
            cancelled = agent.cancel_run(run_id=run_id)

        if not cancelled:
            raise Exception("Failed to cancel run")

        return {"message": f"Run {run_id} cancelled successfully"}

    @mcp.tool(
        name="continue_agent_run",
        description="Continue a paused or incomplete agent run with updated tool results",
        tags={"agents"},
    )  # type: ignore
    async def continue_agent_run(
        ctx: Context,
        agent_id: str,
        run_id: str,
        tools: Optional[List[dict]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        # Check access permission
        require_resource_access(ctx, agent_id, "agents")

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")

        # Use user_id from context if not provided
        if user_id is None:
            user_id = get_user_id_from_context(ctx)

        # Convert tools dict to ToolExecution objects if provided
        from agno.models.response import ToolExecution

        updated_tools: List[ToolExecution] = []
        if tools:
            updated_tools = [ToolExecution.from_dict(tool) for tool in tools]

        run_response = await agent.acontinue_run(
            run_id=run_id,
            updated_tools=updated_tools,
            stream=False,
            user_id=user_id,
            session_id=session_id,
        )
        return run_response.to_dict()
