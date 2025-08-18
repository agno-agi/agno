from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.workflows import WorkflowCreate
from agno.api.settings import agno_api_settings
from agno.utils.log import log_debug


def create_workflow(workflow: WorkflowCreate) -> None:
    if not agno_api_settings.api_enabled:
        return

    with api.AuthenticatedClient() as api_client:
        try:
            api_client.post(
                ApiRoutes.WORKFLOW_CREATE,
                json=workflow.model_dump(exclude_none=True),
            )
        except Exception as e:
            log_debug(f"Could not create Workflow: {e}")


<<<<<<< HEAD
async def acreate_workflow(workflow: WorkflowCreate) -> None:
    if not agno_api_settings.api_enabled:
=======
async def acreate_workflow(workflow: WorkflowRunCreate) -> None:
    if not agno_cli_settings.api_enabled:
>>>>>>> 8f3e6387ff46e5584dc79645d244769a1ea5b96c
        return

    async with api.AuthenticatedAsyncClient() as api_client:
        try:
            await api_client.post(
                ApiRoutes.WORKFLOW_CREATE,
                json=workflow.model_dump(exclude_none=True),
            )
        except Exception as e:
            log_debug(f"Could not create Team: {e}")
