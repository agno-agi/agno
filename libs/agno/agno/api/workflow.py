from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.workflows import WorkflowRunCreate


def create_workflow_run(workflow: WorkflowRunCreate) -> None:
    """Telemetry recording for Workflow runs"""
    api.post_in_background(ApiRoutes.RUN_CREATE, workflow.model_dump(exclude_none=True))


async def acreate_workflow_run(workflow: WorkflowRunCreate) -> None:
    """Telemetry recording for async Workflow runs"""
    await api.apost_in_background(ApiRoutes.RUN_CREATE, workflow.model_dump(exclude_none=True))
