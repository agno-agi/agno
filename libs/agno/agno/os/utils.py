from typing import Any, Callable, Dict, List, Optional, Set, Union

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.routing import APIRoute, APIRouter
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from agno.agent.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.knowledge.knowledge import Knowledge
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.models.message import Message
from agno.os.config import AgentOSConfig
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import logger
from agno.workflow.workflow import Workflow


def get_db(dbs: dict[str, Union[BaseDb, AsyncBaseDb]], db_id: Optional[str] = None) -> Union[BaseDb, AsyncBaseDb]:
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
    """Get the run input from the given run dictionary

    Uses the RunInput/TeamRunInput object which stores the original user input.
    """

    # For agent or team runs, use the stored input_content
    if not is_workflow_run and run_dict.get("input") is not None:
        input_data = run_dict.get("input")
        if isinstance(input_data, dict) and input_data.get("input_content") is not None:
            return stringify_input_content(input_data["input_content"])

    if is_workflow_run:
        # Check the input field directly
        if run_dict.get("input") is not None:
            input_value = run_dict.get("input")
            return str(input_value)

        # Check the step executor runs for fallback
        step_executor_runs = run_dict.get("step_executor_runs", [])
        if step_executor_runs:
            for message in reversed(step_executor_runs[0].get("messages", [])):
                if message.get("role") == "user":
                    return message.get("content", "")

    # Final fallback: scan messages
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
        runs = session.get("runs", []) or []

        # For teams, identify the first Team run and avoid using the first member's run
        if session.get("session_type") == "team":
            run = None
            for r in runs:
                # If agent_id is not present, it's a team run
                if not r.get("agent_id"):
                    run = r
                    break

            # Fallback to first run if no team run found
            if run is None and runs:
                run = runs[0]

        elif session.get("session_type") == "workflow":
            try:
                workflow_run = runs[0]
                workflow_input = workflow_run.get("input")
                if isinstance(workflow_input, str):
                    return workflow_input
                elif isinstance(workflow_input, dict):
                    try:
                        import json

                        return json.dumps(workflow_input)
                    except (TypeError, ValueError):
                        pass

                workflow_name = session.get("workflow_data", {}).get("name")
                return f"New {workflow_name} Session" if workflow_name else ""
            except (KeyError, IndexError, TypeError):
                return ""

        # For agents, use the first run
        else:
            run = runs[0] if runs else None

        if run is None:
            return ""

        if not isinstance(run, dict):
            run = run.to_dict()

        if run and run.get("messages"):
            for message in run["messages"]:
                if message["role"] == "user":
                    return message["content"]
    return ""


def extract_input_media(run_dict: Dict[str, Any]) -> Dict[str, Any]:
    input_media: Dict[str, List[Any]] = {
        "images": [],
        "videos": [],
        "audios": [],
        "files": [],
    }

    input = run_dict.get("input", [])
    input_media["images"].extend(input.get("images", []))
    input_media["videos"].extend(input.get("videos", []))
    input_media["audios"].extend(input.get("audios", []))
    input_media["files"].extend(input.get("files", []))

    return input_media


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


def extract_format(file: UploadFile) -> Optional[str]:
    """Extract the File format from file name or content_type."""
    # Get the format from the filename
    if file.filename and "." in file.filename:
        return file.filename.split(".")[-1].lower()

    # Fallback to the file content_type
    if file.content_type:
        return file.content_type.strip().split("/")[-1]

    return None


def format_tools(agent_tools: List[Union[Dict[str, Any], Toolkit, Function, Callable]]):
    formatted_tools: List[Dict] = []
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
                origins_value = middleware.kwargs.get("allow_origins", [])
                if isinstance(origins_value, list):
                    existing_origins = origins_value
                else:
                    existing_origins = []
            break
    # Merge origins
    merged_origins = list(set(new_origins + existing_origins))
    final_origins = [origin for origin in merged_origins if origin != "*"]

    # Remove existing CORS
    app.user_middleware = [m for m in app.user_middleware if m.cls != CORSMiddleware]
    app.middleware_stack = None

    # Add updated CORS
    app.add_middleware(
        CORSMiddleware,  # type: ignore
        allow_origins=final_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


def get_existing_route_paths(fastapi_app: FastAPI) -> Dict[str, List[str]]:
    """Get all existing route paths and methods from the FastAPI app.

    Returns:
        Dict[str, List[str]]: Dictionary mapping paths to list of HTTP methods
    """
    existing_paths: Dict[str, Any] = {}
    for route in fastapi_app.routes:
        if isinstance(route, APIRoute):
            path = route.path
            methods = list(route.methods) if route.methods else []
            if path in existing_paths:
                existing_paths[path].extend(methods)
            else:
                existing_paths[path] = methods
    return existing_paths


def find_conflicting_routes(fastapi_app: FastAPI, router: APIRouter) -> List[Dict[str, Any]]:
    """Find conflicting routes in the FastAPI app.

    Args:
        fastapi_app: The FastAPI app with all existing routes
        router: The APIRouter to add

    Returns:
        List[Dict[str, Any]]: List of conflicting routes
    """
    existing_paths = get_existing_route_paths(fastapi_app)

    conflicts = []

    for route in router.routes:
        if isinstance(route, APIRoute):
            full_path = route.path
            route_methods = list(route.methods) if route.methods else []

            if full_path in existing_paths:
                conflicting_methods: Set[str] = set(route_methods) & set(existing_paths[full_path])
                if conflicting_methods:
                    conflicts.append({"path": full_path, "methods": list(conflicting_methods), "route": route})
    return conflicts


def load_yaml_config(config_file_path: str) -> AgentOSConfig:
    """Load a YAML config file and return the configuration as an AgentOSConfig instance."""
    from pathlib import Path

    import yaml

    # Validate that the path points to a YAML file
    path = Path(config_file_path)
    if path.suffix.lower() not in [".yaml", ".yml"]:
        raise ValueError(f"Config file must have a .yaml or .yml extension, got: {config_file_path}")

    # Load the YAML file
    with open(config_file_path, "r") as f:
        return AgentOSConfig.model_validate(yaml.safe_load(f))


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


def stringify_input_content(input_content: Union[str, Dict[str, Any], List[Any], BaseModel]) -> str:
    """Convert any given input_content into its string representation.

    This handles both serialized (dict) and live (object) input_content formats.
    """
    import json

    if isinstance(input_content, str):
        return input_content
    elif isinstance(input_content, Message):
        return json.dumps(input_content.to_dict())
    elif isinstance(input_content, dict):
        return json.dumps(input_content, indent=2, default=str)
    elif isinstance(input_content, list):
        if input_content:
            # Handle live Message objects
            if isinstance(input_content[0], Message):
                return json.dumps([m.to_dict() for m in input_content])
            # Handle serialized Message dicts
            elif isinstance(input_content[0], dict) and input_content[0].get("role") == "user":
                return input_content[0].get("content", str(input_content))
        return str(input_content)
    else:
        return str(input_content)
