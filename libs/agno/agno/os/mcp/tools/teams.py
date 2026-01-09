"""Team MCP tools for listing, getting, and managing team runs."""

from typing import TYPE_CHECKING, List

from fastmcp import Context, FastMCP

from agno.os.mcp.auth import filter_teams_by_access, is_authorization_enabled, require_resource_access
from agno.os.routers.teams.schema import TeamResponse
from agno.os.utils import get_team_by_id
from agno.team.remote import RemoteTeam

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_team_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register team management MCP tools."""

    @mcp.tool(
        name="list_teams",
        description="Get a list of all teams configured in this OS instance",
        tags={"teams"},
    )  # type: ignore
    async def list_teams(ctx: Context) -> List[dict]:
        if os.teams is None:
            return []

        # Filter teams based on user's scopes
        accessible_teams = filter_teams_by_access(ctx, os.teams)

        # Check if user has any access at all
        if is_authorization_enabled(ctx) and not accessible_teams:
            raise Exception("Insufficient permissions to access teams")

        teams = []
        for team in accessible_teams:
            if isinstance(team, RemoteTeam):
                team_response = await team.get_team_config()
            else:
                team_response = await TeamResponse.from_team(team=team)
            teams.append(team_response.model_dump(exclude_none=True))

        return teams

    @mcp.tool(
        name="get_team",
        description="Get detailed configuration and member information for a specific team by ID",
        tags={"teams"},
    )  # type: ignore
    async def get_team(ctx: Context, team_id: str) -> dict:
        # Check access permission
        require_resource_access(ctx, team_id, "teams")

        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise Exception(f"Team {team_id} not found")

        if isinstance(team, RemoteTeam):
            team_response = await team.get_team_config()
        else:
            team_response = await TeamResponse.from_team(team)
        return team_response.model_dump(exclude_none=True)

    @mcp.tool(
        name="cancel_team_run",
        description="Cancel a currently executing team run",
        tags={"teams"},
    )  # type: ignore
    async def cancel_team_run(ctx: Context, team_id: str, run_id: str) -> dict:
        # Check access permission
        require_resource_access(ctx, team_id, "teams")

        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise Exception(f"Team {team_id} not found")

        # RemoteTeam.cancel_run is async, Team.cancel_run is sync
        if isinstance(team, RemoteTeam):
            cancelled = await team.cancel_run(run_id=run_id)
        else:
            cancelled = team.cancel_run(run_id=run_id)

        if not cancelled:
            raise Exception("Failed to cancel team run")

        return {"message": f"Team run {run_id} cancelled successfully"}
