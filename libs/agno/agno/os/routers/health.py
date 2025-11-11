from datetime import datetime, timezone

from fastapi import APIRouter

from agno.os.schema import HealthResponse


def get_health_router() -> APIRouter:
    router = APIRouter(tags=["Health"])

    started_time_stamp = datetime.now(timezone.utc).timestamp()

    @router.get(
        "/health",
        operation_id="health_check",
        summary="Health Check",
        description="Check the health status of the AgentOS API. Returns a simple status indicator.",
        response_model=HealthResponse,
        responses={
            200: {
                "description": "API is healthy and operational",
                "content": {"application/json": {"example": {"status": "ok", "instantiated_at": "1760169236.778903"}}},
            }
        },
    )
    async def health_check() -> HealthResponse:
        return HealthResponse(status="ok", instantiated_at=str(started_time_stamp))

    return router
