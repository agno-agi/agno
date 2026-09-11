from typing import TYPE_CHECKING, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_home_router(os: "AgentOS") -> APIRouter:
    """Create the root landing route: a tiny, stable response for anyone hitting the bare URL.

    Points visitors at the real endpoints: /docs (when enabled) for exploration,
    /info for machine-readable metadata, /health for probes. Not part of the API
    contract, so it is excluded from the OpenAPI schema.
    """
    router = APIRouter(tags=["Home"])

    @router.get("/", include_in_schema=False)
    async def home() -> JSONResponse:
        payload: Dict[str, str] = {
            "name": os.name or "AgentOS",
            "health": "/health",
            "info": "/info",
        }
        if os.settings.docs_enabled:
            payload["docs"] = "/docs"
        return JSONResponse(payload)

    return router
