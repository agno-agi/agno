from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.workflows import WorkflowRunCreate
from agno.utils.log import log_debug


def create_workflow_run(workflow: WorkflowRunCreate) -> None:
    """Telemetry recording for Workflow runs"""
    with api.Client() as api_client:
        try:
            api_client.post(
                ApiRoutes.RUN_CREATE,
                json=workflow.model_dump(exclude_none=True),
            )
        except Exception as e:
            log_debug(f"Could not create Workflow: {e}")


async def acreate_workflow_run(workflow: WorkflowRunCreate) -> None:
    """Telemetry recording for async Workflow runs"""
    async with api.AsyncClient() as api_client:
        try:
            await api_client.post(
                ApiRoutes.RUN_CREATE,
                json=workflow.model_dump(exclude_none=True),
            )
        except Exception as e:
            log_debug(f"Could not create Team: {e}")
