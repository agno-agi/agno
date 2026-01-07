"""Workflow MCP tools for listing, getting, and managing workflow runs."""

from typing import TYPE_CHECKING, List

from fastmcp import Context, FastMCP

from agno.os.mcp.auth import filter_workflows_by_access, is_authorization_enabled, require_resource_access
from agno.os.routers.workflows.schema import WorkflowResponse
from agno.os.schema import WorkflowSummaryResponse
from agno.os.utils import get_workflow_by_id
from agno.workflow.remote import RemoteWorkflow

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_workflow_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register workflow management MCP tools."""

    @mcp.tool(
        name="list_workflows",
        description="Get a list of all workflows configured in this OS instance",
        tags={"workflows"},
    )  # type: ignore
    async def list_workflows(ctx: Context) -> List[dict]:
        if os.workflows is None:
            return []

        # Filter workflows based on user's scopes
        accessible_workflows = filter_workflows_by_access(ctx, os.workflows)

        # Check if user has any access at all
        if is_authorization_enabled(ctx) and not accessible_workflows:
            raise Exception("Insufficient permissions to access workflows")

        return [
            WorkflowSummaryResponse.from_workflow(workflow).model_dump(exclude_none=True)
            for workflow in accessible_workflows
        ]

    @mcp.tool(
        name="get_workflow",
        description="Get detailed configuration and step information for a specific workflow by ID",
        tags={"workflows"},
    )  # type: ignore
    async def get_workflow(ctx: Context, workflow_id: str) -> dict:
        # Check access permission
        require_resource_access(ctx, workflow_id, "workflows")

        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise Exception(f"Workflow {workflow_id} not found")

        if isinstance(workflow, RemoteWorkflow):
            workflow_response = await workflow.get_workflow_config()
        else:
            workflow_response = await WorkflowResponse.from_workflow(workflow)
        return workflow_response.model_dump(exclude_none=True)

    @mcp.tool(
        name="cancel_workflow_run",
        description="Cancel a currently executing workflow run",
        tags={"workflows"},
    )  # type: ignore
    async def cancel_workflow_run(ctx: Context, workflow_id: str, run_id: str) -> dict:
        # Check access permission
        require_resource_access(ctx, workflow_id, "workflows")

        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise Exception(f"Workflow {workflow_id} not found")

        # RemoteWorkflow.cancel_run is async, Workflow.cancel_run is sync
        if isinstance(workflow, RemoteWorkflow):
            cancelled = await workflow.cancel_run(run_id=run_id)
        else:
            cancelled = workflow.cancel_run(run_id=run_id)

        if not cancelled:
            raise Exception("Failed to cancel workflow run")

        return {"message": f"Workflow run {run_id} cancelled successfully"}
