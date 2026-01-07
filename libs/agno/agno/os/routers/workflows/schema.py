from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, model_serializer

from agno.os.routers.agents.schema import AgentMinimalResponse
from agno.os.routers.teams.schema import TeamMinimalResponse
from agno.os.schema import DatabaseConfigResponse
from agno.os.utils import get_workflow_input_schema_dict, remove_none_values
from agno.workflow.agent import WorkflowAgent
from agno.workflow import Workflow, RemoteWorkflow


class WorkflowMinimalResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the workflow")
    name: Optional[str] = Field(None, description="Name of the workflow")
    description: Optional[str] = Field(None, description="Description of the workflow")
    db_id: Optional[str] = Field(None, description="Database identifier")

    @classmethod
    def from_workflow(cls, workflow: Union[Workflow, RemoteWorkflow]) -> "WorkflowMinimalResponse":
        db_id = workflow.db.id if workflow.db else None
        return cls(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            db_id=db_id,
        )



class StepTypeResponse(str, Enum):
    """The type of workflow step"""
    FUNCTION = "Function"
    STEP = "Step"
    STEPS = "Steps"
    LOOP = "Loop"
    PARALLEL = "Parallel"
    CONDITION = "Condition"
    ROUTER = "Router"


class StepResponse(BaseModel):
    """A workflow step definition"""
    name: Optional[str] = Field(None, description="The name of the step")
    description: Optional[str] = Field(None, description="The description of the step")
    type: Optional[StepTypeResponse] = Field(None, description="The type of the step")

    # Executor configuration (only one should be present)
    agent: Optional[Dict[str, Any]] = Field(None, description="The agent configuration if this step uses an agent")
    team: Optional[Dict[str, Any]] = Field(None, description="The team configuration if this step uses a team")

    # Nested steps for container types (Steps, Loop, Parallel, Condition, Router)
    steps: Optional[List["StepResponse"]] = Field(None, description="Nested steps for container step types")

    # Step configuration
    max_retries: Optional[int] = Field(None, description="Maximum retry attempts for the step")
    timeout_seconds: Optional[int] = Field(None, description="Timeout in seconds for step execution")
    skip_on_failure: Optional[bool] = Field(None, description="Whether to skip this step on failure")

    # Loop-specific configuration
    max_iterations: Optional[int] = Field(None, description="Maximum iterations for Loop steps")

    # Additional metadata
    step_id: Optional[str] = Field(None, description="Unique identifier for the step")


class WorkflowResponse(BaseModel):
    id: str = Field(..., description="The ID of the workflow")
    name: Optional[str] = Field(None, description="The name of the workflow")
    description: Optional[str] = Field(None, description="The description of the workflow")
    database: Optional[DatabaseConfigResponse] = Field(None, description="The database of the workflow")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="The input schema of the workflow")
    steps: Optional[List[StepResponse]] = Field(None, description="The steps of the workflow")
    metadata: Optional[Dict[str, Any]] = Field(None, description="The metadata of the workflow")
    workflow_agent: bool = Field(False, description="Whether this workflow uses a WorkflowAgent")

    @model_serializer(mode="wrap")
    def serialize_model(self, handler) -> Dict[str, Any]:
        """Custom serializer that recursively removes None values from nested structures."""
        data = handler(self)
        return remove_none_values(data)

    @classmethod
    async def _resolve_step_recursively(cls, step_dict: Dict[str, Any]) -> StepResponse:
        """Convert a step dictionary to a StepResponse, resolving agents and teams."""

        # Resolve agent if present
        agent_data: Optional[Dict[str, Any]] = None
        if step_dict.get("agent"):
            agent_response = AgentMinimalResponse.from_agent(step_dict["agent"])
            agent_data = agent_response.model_dump(exclude_none=True)

        # Resolve team if present
        team_data: Optional[Dict[str, Any]] = None
        if step_dict.get("team"):
            team_response = TeamMinimalResponse.from_team(step_dict["team"])
            team_data = team_response.model_dump(exclude_none=True)

        # Recursively resolve nested steps
        nested_steps: Optional[List[StepResponse]] = None
        if step_dict.get("steps"):
            nested_steps = []
            for nested_step in step_dict["steps"]:
                resolved_step = await cls._resolve_step_recursively(nested_step)
                nested_steps.append(resolved_step)

        # Map step type string to enum
        step_type: Optional[StepTypeResponse] = None
        if step_dict.get("type"):
            try:
                step_type = StepTypeResponse(step_dict["type"])
            except ValueError:
                step_type = None

        return StepResponse(
            name=step_dict.get("name"),
            description=step_dict.get("description"),
            type=step_type,
            agent=agent_data,
            team=team_data,
            steps=nested_steps,
            max_retries=step_dict.get("max_retries"),
            timeout_seconds=step_dict.get("timeout_seconds"),
            skip_on_failure=step_dict.get("skip_on_failure"),
            max_iterations=step_dict.get("max_iterations"),
            step_id=step_dict.get("step_id"),
        )

    @classmethod
    async def _resolve_steps(cls, steps: List[Dict[str, Any]]) -> List[StepResponse]:
        """Convert a list of step dictionaries to StepResponse objects."""
        resolved_steps: List[StepResponse] = []
        for step_dict in steps:
            resolved_step = await cls._resolve_step_recursively(step_dict)
            resolved_steps.append(resolved_step)
        return resolved_steps

    @classmethod
    async def from_workflow(cls, workflow: Workflow) -> "WorkflowResponse":
        workflow_dict = workflow.to_dict()
        raw_steps = workflow_dict.get("steps")

        steps: Optional[List[StepResponse]] = None
        if raw_steps:
            steps = await cls._resolve_steps(raw_steps)

        database: Optional[DatabaseConfigResponse] = None
        if workflow.db:
            table_names, config = workflow.db.to_config()
            database = DatabaseConfigResponse(
                id=workflow.db.id,
                table_names=table_names,
                config=config,
            )

        return cls(
            id=workflow.id,
            name=workflow.name,
            database=database,
            description=workflow.description,
            steps=steps,
            input_schema=get_workflow_input_schema_dict(workflow),
            metadata=workflow.metadata,
            workflow_agent=isinstance(workflow.agent, WorkflowAgent) if workflow.agent else False,
        )
