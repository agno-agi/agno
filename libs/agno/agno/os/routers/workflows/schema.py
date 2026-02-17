from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agno.os.routers.agents.schema import AgentResponse
from agno.os.routers.teams.schema import TeamResponse
from agno.workflow.agent import WorkflowAgent
from agno.workflow.workflow import Workflow


def _generate_schema_from_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Convert function parameters to JSON schema"""
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for param_name, param_info in params.items():
        # Skip the default 'message' parameter for custom kwargs workflows
        if param_name == "message":
            continue

        # Map Python types to JSON schema types
        param_type = param_info.get("annotation", "str")
        default_value = param_info.get("default")
        is_required = param_info.get("required", False)

        # Convert Python type annotations to JSON schema types
        if param_type == "str":
            properties[param_name] = {"type": "string"}
        elif param_type == "bool":
            properties[param_name] = {"type": "boolean"}
        elif param_type == "int":
            properties[param_name] = {"type": "integer"}
        elif param_type == "float":
            properties[param_name] = {"type": "number"}
        elif "List" in str(param_type):
            properties[param_name] = {"type": "array", "items": {"type": "string"}}
        else:
            properties[param_name] = {"type": "string"}  # fallback

        # Add default value if present
        if default_value is not None:
            properties[param_name]["default"] = default_value

        # Add to required if no default value
        if is_required and default_value is None:
            required.append(param_name)

    schema = {"type": "object", "properties": properties}

    if required:
        schema["required"] = required

    return schema


def get_workflow_input_schema_dict(workflow: Workflow) -> Optional[Dict[str, Any]]:
    """Get input schema as dictionary for API responses"""

    # Priority 1: Explicit input_schema (Pydantic model)
    if workflow.input_schema is not None:
        try:
            return workflow.input_schema.model_json_schema()
        except Exception:
            return None

    # Priority 2: Auto-generate from custom kwargs
    if workflow.steps and callable(workflow.steps):
        custom_params = workflow.run_parameters
        if custom_params and len(custom_params) > 1:  # More than just 'message'
            return _generate_schema_from_params(custom_params)

    # Priority 3: No schema (expects string message)
    return None


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
    is_component: bool = Field(False, description="Whether this workflow was created via Builder")
    current_version: Optional[int] = Field(None, description="Current published version number")
    stage: Optional[str] = Field(None, description="Stage of the loaded config (draft/published)")

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
    async def from_workflow(
        cls,
        workflow: Workflow,
        is_component: bool = False,
    ) -> "WorkflowResponse":
        workflow_dict = workflow.to_dict_for_steps()
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
            is_component=is_component,
            current_version=getattr(workflow, "_version", None),
            stage=getattr(workflow, "_stage", None),
        )
