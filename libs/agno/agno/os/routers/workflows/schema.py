from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agno.os.routers.agents.schema import AgentResponse
from agno.os.routers.teams.schema import TeamResponse
from agno.os.utils import get_workflow_input_schema_dict
from agno.workflow.agent import WorkflowAgent
from agno.workflow.workflow import Workflow


class WorkflowResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the workflow")
    name: Optional[str] = Field(None, description="Name of the workflow")
    db_id: Optional[str] = Field(None, description="Database identifier")
    description: Optional[str] = Field(None, description="Description of the workflow")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="Input schema for the workflow")
    steps: Optional[List[Dict[str, Any]]] = Field(None, description="List of workflow steps")
    agent: Optional[AgentResponse] = Field(None, description="Agent configuration if used")
    team: Optional[TeamResponse] = Field(None, description="Team configuration if used")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    workflow_agent: bool = Field(False, description="Whether this workflow uses a WorkflowAgent")

    @classmethod
    async def _resolve_agents_and_teams_recursively(cls, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse Agents and Teams into AgentResponse and TeamResponse objects.

        If the given steps have nested steps, recursively work on those."""
        if not steps:
            return steps

        def _prune_none(value: Any) -> Any:
            # Recursively remove None values from dicts and lists
            if isinstance(value, dict):
                return {k: _prune_none(v) for k, v in value.items() if v is not None}
            if isinstance(value, list):
                return [_prune_none(v) for v in value]
            return value

        for idx, step in enumerate(steps):
            if step.get("agent"):
                # Convert to dict and exclude fields that are None
                agent_response = await AgentResponse.from_agent(step.get("agent"))  # type: ignore
                step["agent"] = agent_response.model_dump(exclude_none=True)

            if step.get("team"):
                team_response = await TeamResponse.from_team(step.get("team"))  # type: ignore
                step["team"] = team_response.model_dump(exclude_none=True)

            if step.get("steps"):
                step["steps"] = await cls._resolve_agents_and_teams_recursively(step["steps"])

            # Prune None values in the entire step
            steps[idx] = _prune_none(step)

        return steps

    @classmethod
    async def from_workflow(cls, workflow: Workflow) -> "WorkflowResponse":
        workflow_dict = workflow.to_dict()
        steps = workflow_dict.get("steps")

        if steps:
            steps = await cls._resolve_agents_and_teams_recursively(steps)

        return cls(
            id=workflow.id,
            name=workflow.name,
            db_id=workflow.db.id if workflow.db else None,
            description=workflow.description,
            steps=steps,
            input_schema=get_workflow_input_schema_dict(workflow),
            metadata=workflow.metadata,
            workflow_agent=isinstance(workflow.agent, WorkflowAgent) if workflow.agent else False,
        )
