from fastapi import APIRouter

from agno.os.schema import HealthResponse


def get_health_router() -> APIRouter:
    router = APIRouter(tags=["Health"])

    @router.get(
        "/health",
        operation_id="health_check",
        summary="Health Check",
        description="Check the health status of the AgentOS API. Returns a simple status indicator.",
        response_model=HealthResponse,
        responses={
            200: {
                "description": "API is healthy and operational",
                "content": {"application/json": {"example": {"status": "ok"}}},
            }
        },
    )
    async def health_check() -> HealthResponse:
        return HealthResponse(status="ok")

    return router
