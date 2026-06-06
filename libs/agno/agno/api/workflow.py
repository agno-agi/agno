import threading

from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.workflows import WorkflowRunCreate
from agno.utils.log import log_debug


def _send_workflow_run(workflow: WorkflowRunCreate) -> None:
    """Send workflow run telemetry via HTTP (called from background thread)."""
    with api.Client() as api_client:
        try:
            api_client.post(
                ApiRoutes.RUN_CREATE,
                json=workflow.model_dump(exclude_none=True),
            )
        except Exception as e:
            log_debug(f"Could not create Workflow: {e}")


def create_workflow_run(workflow: WorkflowRunCreate) -> None:
    """Telemetry recording for Workflow runs (fire-and-forget in background thread)."""
    threading.Thread(target=_send_workflow_run, args=(workflow,), daemon=True).start()


async def acreate_workflow_run(workflow: WorkflowRunCreate) -> None:
    """Telemetry recording for async Workflow runs (fire-and-forget via executor)."""
    import asyncio

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _send_workflow_run, workflow)
