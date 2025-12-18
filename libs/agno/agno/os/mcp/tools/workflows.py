"""Workflow MCP tools for listing, getting, and managing workflow runs."""

from typing import TYPE_CHECKING, List

from fastmcp import FastMCP

from agno.os.routers.workflows.schema import WorkflowResponse
from agno.os.schema import WorkflowSummaryResponse
from agno.os.utils import get_workflow_by_id

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_workflow_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register workflow management MCP tools."""

    @mcp.tool(
        name="list_workflows",
        description="Get a list of all workflows configured in this OS instance",
        tags={"workflows"},
    )  # type: ignore
    async def list_workflows() -> List[dict]:
        if os.workflows is None:
            return []

        return [
            WorkflowSummaryResponse.from_workflow(workflow).model_dump(exclude_none=True)
            for workflow in os.workflows
        ]

    @mcp.tool(
        name="get_workflow",
        description="Get detailed configuration and step information for a specific workflow by ID",
        tags={"workflows"},
    )  # type: ignore
    async def get_workflow(workflow_id: str) -> dict:
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise Exception(f"Workflow {workflow_id} not found")

        workflow_response = await WorkflowResponse.from_workflow(workflow)
        return workflow_response.model_dump(exclude_none=True)

    @mcp.tool(
        name="cancel_workflow_run",
        description="Cancel a currently executing workflow run",
        tags={"workflows"},
    )  # type: ignore
    async def cancel_workflow_run(workflow_id: str, run_id: str) -> dict:
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise Exception(f"Workflow {workflow_id} not found")

        if not workflow.cancel_run(run_id=run_id):
            raise Exception("Failed to cancel workflow run")

        return {"message": f"Workflow run {run_id} cancelled successfully"}

