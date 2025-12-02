from typing import TYPE_CHECKING, List

from fastapi import APIRouter, Depends, HTTPException

from agno.os.auth import get_authentication_dependency
from agno.os.routers.workflows.schema import WorkflowResponse
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_workflow_by_id

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_workflows_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """
    Create the base FastAPI router with comprehensive OpenAPI documentation.

    This router provides endpoints for:
    - Core system operations (health, config, models)
    - Agent management and execution
    - Team collaboration and coordination
    - Workflow automation and orchestration

    All endpoints include detailed documentation, examples, and proper error handling.
    """
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.get(
        "/workflows",
        response_model=List[WorkflowResponse],
        response_model_exclude_none=True,
        tags=["Workflows"],
        operation_id="get_workflows",
        summary="List All Workflows",
        description=(
            "Retrieve a comprehensive list of all workflows configured in this OS instance.\n\n"
            "**Return Information:**\n"
            "- Workflow metadata (ID, name, description)\n"
            "- Input schema requirements\n"
            "- Step sequence and execution flow\n"
            "- Associated agents and teams"
        ),
        responses={
            200: {
                "description": "List of workflows retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "content-creation-workflow",
                                "name": "Content Creation Workflow",
                                "description": "Automated content creation from blog posts to social media",
                                "db_id": "123",
                            }
                        ]
                    }
                },
            }
        },
    )
    async def get_workflows() -> List[WorkflowResponse]:
        if os.workflows is None:
            return []

        return [WorkflowResponse.from_workflow(workflow) for workflow in os.workflows]

    @router.get(
        "/workflows/{workflow_id}",
        response_model=WorkflowResponse,
        response_model_exclude_none=True,
        tags=["Workflows"],
        operation_id="get_workflow",
        summary="Get Workflow Details",
        description=("Retrieve detailed configuration and step information for a specific workflow."),
        responses={
            200: {
                "description": "Workflow details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "content-creation-workflow",
                            "name": "Content Creation Workflow",
                            "description": "Automated content creation from blog posts to social media",
                            "db_id": "123",
                        }
                    }
                },
            },
            404: {"description": "Workflow not found", "model": NotFoundResponse},
        },
    )
    async def get_workflow(workflow_id: str) -> WorkflowResponse:
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return await WorkflowResponse.from_workflow(workflow)

    return router
