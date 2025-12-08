from typing import Any, Dict, List

from fastapi import APIRouter

from agno.os.builder.config import BuilderConfig
from agno.os.builder.models import (
    BuilderAgentRequest,
    BuilderConfigResponse,
    BuilderDatabaseResponse,
    BuilderModelResponse,
    BuilderToolResponse,
)
from agno.os.utils import format_tools


def get_builder_router(builder: BuilderConfig) -> APIRouter:
    router = APIRouter(prefix="/builder", tags=["Builder"])

    @router.get("/config", response_model=BuilderConfigResponse)
    async def get_builder_config():
        from agno.tools import Toolkit
        from agno.tools.function import Function

        tools: List[BuilderToolResponse] = []
        if builder.tools:
            for tool in builder.tools:
                if isinstance(tool, Toolkit):
                    tools.append(
                        BuilderToolResponse(
                            id=tool.name,
                            name=tool.name,
                            description=tool.__doc__ or tool.instructions,
                        )
                    )
                elif isinstance(tool, Function):
                    tools.append(
                        BuilderToolResponse(
                            id=tool.name,
                            name=tool.name,
                            description=tool.description,
                        )
                    )

        models: List[BuilderModelResponse] = []
        if builder.models:
            for m in builder.models:
                models.append(
                    BuilderModelResponse(
                        name=getattr(m, "name", None),
                        model=getattr(m, "id", None),
                        provider=getattr(m, "provider", None),
                    )
                )

        databases: List[BuilderDatabaseResponse] = []
        if builder.databases:
            for db in builder.databases:
                databases.append(
                    BuilderDatabaseResponse(
                        id=db.id,
                        type=db.__class__.__name__,
                    )
                )

        return BuilderConfigResponse(
            tools=tools,
            models=models,
            databases=databases,
        )

    # Purely for adding the response model to our swagger docs
    # TODO: REMOVE AFTER TESTING
    @router.post("/agents", response_model=BuilderAgentRequest)
    async def create_agent(agent: BuilderAgentRequest):
        """
        Create a new agent configuration.
        """

        return agent

    return router
