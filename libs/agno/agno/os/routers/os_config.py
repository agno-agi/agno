from typing import TYPE_CHECKING

from fastapi import APIRouter

from agno.os.schema import OSConfigResponse

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_os_config_router(os: "AgentOS") -> APIRouter:
    """Create an unauthenticated router that exposes lightweight OS metadata."""
    router = APIRouter(tags=["Core"])

    @router.get(
        "/os/config",
        operation_id="get_os_config",
        summary="Get OS Config",
        description="Retrieve lightweight OS metadata including component counts. This endpoint is unauthenticated.",
        response_model=OSConfigResponse,
        responses={
            200: {
                "description": "OS config retrieved successfully",
                "content": {"application/json": {"example": {"agent_count": 2, "team_count": 1, "workflow_count": 0}}},
            }
        },
    )
    async def os_config() -> OSConfigResponse:
        return OSConfigResponse(
            agent_count=len(os.agents) if os.agents else 0,
            team_count=len(os.teams) if os.teams else 0,
            workflow_count=len(os.workflows) if os.workflows else 0,
        )

    return router
