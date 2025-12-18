"""Agent MCP tools for listing, getting, and managing agent runs."""

from typing import TYPE_CHECKING, List, Optional

from fastmcp import FastMCP

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
    async def list_agents() -> List[dict]:
        if os.agents is None:
            return []

        agents = []
        for agent in os.agents:
            agent_response = await AgentResponse.from_agent(agent=agent)
            agents.append(agent_response.model_dump(exclude_none=True))

        return agents

    @mcp.tool(
        name="get_agent",
        description="Get detailed configuration and capabilities of a specific agent by ID",
        tags={"agents"},
    )  # type: ignore
    async def get_agent(agent_id: str) -> dict:
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")

        agent_response = await AgentResponse.from_agent(agent)
        return agent_response.model_dump(exclude_none=True)

    @mcp.tool(
        name="cancel_agent_run",
        description="Cancel a currently executing agent run",
        tags={"agents"},
    )  # type: ignore
    async def cancel_agent_run(agent_id: str, run_id: str) -> dict:
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")

        if not agent.cancel_run(run_id=run_id):
            raise Exception("Failed to cancel run")

        return {"message": f"Run {run_id} cancelled successfully"}

    @mcp.tool(
        name="continue_agent_run",
        description="Continue a paused or incomplete agent run with updated tool results",
        tags={"agents"},
    )  # type: ignore
    async def continue_agent_run(
        agent_id: str,
        run_id: str,
        tools: Optional[List[dict]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")

        # Convert tools dict to ToolExecution objects if provided
        updated_tools = None
        if tools:
            from agno.models.response import ToolExecution

            updated_tools = [ToolExecution.from_dict(tool) for tool in tools]

        run_response = await agent.acontinue_run(
            run_id=run_id,
            updated_tools=updated_tools,
            session_id=session_id,
            user_id=user_id,
            stream=False,
        )
        return run_response.to_dict()

