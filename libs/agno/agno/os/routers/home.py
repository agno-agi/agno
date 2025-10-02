from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_home_router(os: "AgentOS") -> APIRouter:
    router = APIRouter(tags=["Home"])

    @router.get(
        "/",
        operation_id="get_api_info",
        summary="API Information",
        description=(
            "Get basic information about this AgentOS API instance, including:\n\n"
            "- API metadata and version\n"
            "- Available capabilities overview\n"
            "- Links to key endpoints and documentation"
        ),
        responses={
            200: {
                "description": "API information retrieved successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "home": {
                                "summary": "Example home response",
                                "value": {
                                    "name": "AgentOS API",
                                    "description": "AI Agent Operating System API",
                                    "id": "demo-os",
                                    "version": "1.0.0",
                                },
                            }
                        }
                    }
                },
            }
        },
    )
    async def get_api_info():
        """Get basic API information and available capabilities"""
        return {
            "name": "AgentOS API",
            "description": os.description or "AI Agent Operating System API",
            "id": os.id or "agno-agentos",
            "version": os.version or "1.0.0",
        }

    return router
