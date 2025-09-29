from typing import Any, Callable, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException, UploadFile
from starlette.middleware.cors import CORSMiddleware

from agno.agent.agent import Agent
from agno.db.base import BaseDb
from agno.knowledge.knowledge import Knowledge
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import logger
from agno.workflow.workflow import Workflow


def get_db(dbs: dict[str, BaseDb], db_id: Optional[str] = None) -> BaseDb:
    """Return the database with the given ID, or the first database if no ID is provided."""

    # Raise if multiple databases are provided but no db_id is provided
    if not db_id and len(dbs) > 1:
        raise HTTPException(
            status_code=400, detail="The db_id query parameter is required when using multiple databases"
        )

    # Get and return the database with the given ID, or raise if not found
    if db_id:
        db = dbs.get(db_id)
        if not db:
            raise HTTPException(status_code=404, detail=f"Database with id '{db_id}' not found")
    else:
        db = next(iter(dbs.values()))
    return db


def get_knowledge_instance_by_db_id(knowledge_instances: List[Knowledge], db_id: Optional[str] = None) -> Knowledge:
    """Return the knowledge instance with the given ID, or the first knowledge instance if no ID is provided."""
    if not db_id and len(knowledge_instances) == 1:
        return next(iter(knowledge_instances))

    if not db_id:
        raise HTTPException(
            status_code=400, detail="The db_id query parameter is required when using multiple databases"
        )

    for knowledge in knowledge_instances:
        if knowledge.contents_db and knowledge.contents_db.id == db_id:
            return knowledge

    raise HTTPException(status_code=404, detail=f"Knowledge instance with id '{db_id}' not found")


def get_run_input(run_dict: Dict[str, Any], is_workflow_run: bool = False) -> str:
    """Get the run input from the given run dictionary"""

    if is_workflow_run:
        step_executor_runs = run_dict.get("step_executor_runs", [])
        if step_executor_runs:
            for message in reversed(step_executor_runs[0].get("messages", [])):
                if message.get("role") == "user":
                    return message.get("content", "")

        # Check the input field directly as final fallback
        if run_dict.get("input") is not None:
            input_value = run_dict.get("input")
            if isinstance(input_value, str):
                return input_value
            else:
                return str(input_value)

    if run_dict.get("messages") is not None:
        for message in reversed(run_dict["messages"]):
            if message.get("role") == "user":
                return message.get("content", "")

    return ""


def get_session_name(session: Dict[str, Any]) -> str:
    """Get the session name from the given session dictionary"""

    # If session_data.session_name is set, return that
    session_data = session.get("session_data")
    if session_data is not None and session_data.get("session_name") is not None:
        return session_data["session_name"]

    # Otherwise use the original user message
    else:
        runs = session.get("runs", [])

        # For teams, identify the first Team run and avoid using the first member's run
        if session.get("session_type") == "team":
            run = runs[0] if not runs[0].get("agent_id") else runs[1]

        # For workflows, pass along the first step_executor_run
        elif session.get("session_type") == "workflow":
            try:
                run = session["runs"][0]["step_executor_runs"][0]
            except (KeyError, IndexError, TypeError):
                return ""

        # For agents, use the first run
        else:
            run = runs[0]

        if not isinstance(run, dict):
            run = run.to_dict()

        if run and run.get("messages"):
            for message in run["messages"]:
                if message["role"] == "user":
                    return message["content"]
    return ""


def process_image(file: UploadFile) -> Image:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Image(content=content, format=extract_format(file), mime_type=file.content_type)


def process_audio(file: UploadFile) -> Audio:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Audio(content=content, format=extract_format(file), mime_type=file.content_type)


def process_video(file: UploadFile) -> Video:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Video(content=content, format=extract_format(file), mime_type=file.content_type)


def process_document(file: UploadFile) -> Optional[FileMedia]:
    try:
        content = file.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
        return FileMedia(
            content=content, filename=file.filename, format=extract_format(file), mime_type=file.content_type
        )
    except Exception as e:
        logger.error(f"Error processing document {file.filename}: {e}")
        return None


def extract_format(file: UploadFile):
    format = None
    if file.filename and "." in file.filename:
        format = file.filename.split(".")[-1].lower()
    elif file.content_type:
        format = file.content_type.split("/")[-1]
    return format


def format_tools(agent_tools: List[Union[Dict[str, Any], Toolkit, Function, Callable]]):
    formatted_tools = []
    if agent_tools is not None:
        for tool in agent_tools:
            if isinstance(tool, dict):
                formatted_tools.append(tool)
            elif isinstance(tool, Toolkit):
                for _, f in tool.functions.items():
                    formatted_tools.append(f.to_dict())
            elif isinstance(tool, Function):
                formatted_tools.append(tool.to_dict())
            elif callable(tool):
                func = Function.from_callable(tool)
                formatted_tools.append(func.to_dict())
            else:
                logger.warning(f"Unknown tool type: {type(tool)}")
    return formatted_tools


def format_team_tools(team_tools: List[Function]):
    return [tool.to_dict() for tool in team_tools]


def get_agent_by_id(agent_id: str, agents: Optional[List[Agent]] = None) -> Optional[Agent]:
    if agent_id is None or agents is None:
        return None

    for agent in agents:
        if agent.id == agent_id:
            return agent
    return None


def get_team_by_id(team_id: str, teams: Optional[List[Team]] = None) -> Optional[Team]:
    if team_id is None or teams is None:
        return None

    for team in teams:
        if team.id == team_id:
            return team
    return None


def get_workflow_by_id(workflow_id: str, workflows: Optional[List[Workflow]] = None) -> Optional[Workflow]:
    if workflow_id is None or workflows is None:
        return None

    for workflow in workflows:
        if workflow.id == workflow_id:
            return workflow
    return None


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


def update_cors_middleware(app: FastAPI, new_origins: list):
    existing_origins: List[str] = []

    # TODO: Allow more options where CORS is properly merged and user can disable this behaviour

    # Extract existing origins from current CORS middleware
    for middleware in app.user_middleware:
        if middleware.cls == CORSMiddleware:
            if hasattr(middleware, "kwargs"):
                existing_origins = middleware.kwargs.get("allow_origins", [])
            break
    # Merge origins
    merged_origins = list(set(new_origins + existing_origins))
    final_origins = [origin for origin in merged_origins if origin != "*"]

    # Remove existing CORS
    app.user_middleware = [m for m in app.user_middleware if m.cls != CORSMiddleware]
    app.middleware_stack = None

    # Add updated CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=final_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


def collect_mcp_tools_from_team(team: Team, mcp_tools: List[Any]) -> None:
    """Recursively collect MCP tools from a team and its members."""
    # Check the team tools
    if team.tools:
        for tool in team.tools:
            type_name = type(tool).__name__
            if type_name in ("MCPTools", "MultiMCPTools"):
                if tool not in mcp_tools:
                    mcp_tools.append(tool)

    # Recursively check team members
    if team.members:
        for member in team.members:
            if isinstance(member, Agent):
                if member.tools:
                    for tool in member.tools:
                        type_name = type(tool).__name__
                        if type_name in ("MCPTools", "MultiMCPTools"):
                            if tool not in mcp_tools:
                                mcp_tools.append(tool)

            elif isinstance(member, Team):
                # Recursively check nested team
                collect_mcp_tools_from_team(member, mcp_tools)


def collect_mcp_tools_from_workflow(workflow: Workflow, mcp_tools: List[Any]) -> None:
    """Recursively collect MCP tools from a workflow and its steps."""
    from agno.workflow.steps import Steps

    # Recursively check workflow steps
    if workflow.steps:
        if isinstance(workflow.steps, list):
            # Handle list of steps
            for step in workflow.steps:
                collect_mcp_tools_from_workflow_step(step, mcp_tools)

        elif isinstance(workflow.steps, Steps):
            # Handle Steps container
            if steps := workflow.steps.steps:
                for step in steps:
                    collect_mcp_tools_from_workflow_step(step, mcp_tools)

        elif callable(workflow.steps):
            pass


def collect_mcp_tools_from_workflow_step(step: Any, mcp_tools: List[Any]) -> None:
    """Collect MCP tools from a single workflow step."""
    from agno.workflow.condition import Condition
    from agno.workflow.loop import Loop
    from agno.workflow.parallel import Parallel
    from agno.workflow.router import Router
    from agno.workflow.step import Step
    from agno.workflow.steps import Steps

    if isinstance(step, Step):
        # Check step's agent
        if step.agent:
            if step.agent.tools:
                for tool in step.agent.tools:
                    type_name = type(tool).__name__
                    if type_name in ("MCPTools", "MultiMCPTools"):
                        if tool not in mcp_tools:
                            mcp_tools.append(tool)
        # Check step's team
        if step.team:
            collect_mcp_tools_from_team(step.team, mcp_tools)

    elif isinstance(step, Steps):
        if steps := step.steps:
            for step in steps:
                collect_mcp_tools_from_workflow_step(step, mcp_tools)

    elif isinstance(step, (Parallel, Loop, Condition, Router)):
        # These contain other steps - recursively check them
        if hasattr(step, "steps") and step.steps:
            for sub_step in step.steps:
                collect_mcp_tools_from_workflow_step(sub_step, mcp_tools)

    elif isinstance(step, Agent):
        # Direct agent in workflow steps
        if step.tools:
            for tool in step.tools:
                type_name = type(tool).__name__
                if type_name in ("MCPTools", "MultiMCPTools"):
                    if tool not in mcp_tools:
                        mcp_tools.append(tool)

    elif isinstance(step, Team):
        # Direct team in workflow steps
        collect_mcp_tools_from_team(step, mcp_tools)

    elif isinstance(step, Workflow):
        # Nested workflow
        collect_mcp_tools_from_workflow(step, mcp_tools)
