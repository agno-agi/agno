import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.routing import APIRoute, APIRouter
from pydantic import BaseModel, create_model
from starlette.middleware.cors import CORSMiddleware

from agno.agent.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.knowledge.knowledge import Knowledge
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.models.message import Message
from agno.os.config import AgentOSConfig
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import WorkflowRunOutputEvent
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_warning, logger
from agno.workflow.workflow import Workflow


async def get_request_kwargs(request: Request, endpoint_func: Callable) -> Dict[str, Any]:
    """Given a Request and an endpoint function, return a dictionary with all extra form data fields.

    Args:
        request: The FastAPI Request object
        endpoint_func: The function exposing the endpoint that received the request

    Supported form parameters:
        - session_state: JSON string of session state dict
        - dependencies: JSON string of dependencies dict
        - metadata: JSON string of metadata dict
        - knowledge_filters: JSON string of knowledge filters
        - output_schema: JSON schema string (converted to Pydantic model by default)
        - use_json_schema: If "true", keeps output_schema as dict instead of converting to Pydantic model

    Returns:
        A dictionary of kwargs to pass to Agent/Team run methods
    """
    import inspect

    form_data = await request.form()
    sig = inspect.signature(endpoint_func)
    known_fields = set(sig.parameters.keys())
    kwargs: Dict[str, Any] = {key: value for key, value in form_data.items() if key not in known_fields}

    # Handle JSON parameters. They are passed as strings and need to be deserialized.
    if session_state := kwargs.get("session_state"):
        try:
            if isinstance(session_state, str):
                session_state_dict = json.loads(session_state)  # type: ignore
                kwargs["session_state"] = session_state_dict
        except json.JSONDecodeError:
            kwargs.pop("session_state")
            log_warning(f"Invalid session_state parameter couldn't be loaded: {session_state}")

    if dependencies := kwargs.get("dependencies"):
        try:
            if isinstance(dependencies, str):
                dependencies_dict = json.loads(dependencies)  # type: ignore
                kwargs["dependencies"] = dependencies_dict
        except json.JSONDecodeError:
            kwargs.pop("dependencies")
            log_warning(f"Invalid dependencies parameter couldn't be loaded: {dependencies}")

    if metadata := kwargs.get("metadata"):
        try:
            if isinstance(metadata, str):
                metadata_dict = json.loads(metadata)  # type: ignore
                kwargs["metadata"] = metadata_dict
        except json.JSONDecodeError:
            kwargs.pop("metadata")
            log_warning(f"Invalid metadata parameter couldn't be loaded: {metadata}")

    if knowledge_filters := kwargs.get("knowledge_filters"):
        try:
            if isinstance(knowledge_filters, str):
                knowledge_filters_dict = json.loads(knowledge_filters)  # type: ignore

                # Try to deserialize FilterExpr objects
                from agno.filters import from_dict

                # Check if it's a single FilterExpr dict or a list of FilterExpr dicts
                if isinstance(knowledge_filters_dict, dict) and "op" in knowledge_filters_dict:
                    # Single FilterExpr - convert to list format
                    kwargs["knowledge_filters"] = [from_dict(knowledge_filters_dict)]
                elif isinstance(knowledge_filters_dict, list):
                    # List of FilterExprs or mixed content
                    deserialized = []
                    for item in knowledge_filters_dict:
                        if isinstance(item, dict) and "op" in item:
                            deserialized.append(from_dict(item))
                        else:
                            # Keep non-FilterExpr items as-is
                            deserialized.append(item)
                    kwargs["knowledge_filters"] = deserialized
                else:
                    # Regular dict filter
                    kwargs["knowledge_filters"] = knowledge_filters_dict
        except json.JSONDecodeError:
            kwargs.pop("knowledge_filters")
            log_warning(f"Invalid knowledge_filters parameter couldn't be loaded: {knowledge_filters}")
        except ValueError as e:
            # Filter deserialization failed
            kwargs.pop("knowledge_filters")
            log_warning(f"Invalid FilterExpr in knowledge_filters: {e}")

    # Handle output_schema - convert JSON schema to Pydantic model or keep as dict
    # use_json_schema is a control flag consumed here (not passed to Agent/Team)
    # When true, output_schema stays as dict for direct JSON output
    use_json_schema = kwargs.pop("use_json_schema", False)
    if isinstance(use_json_schema, str):
        use_json_schema = use_json_schema.lower() == "true"

    if output_schema := kwargs.get("output_schema"):
        try:
            if isinstance(output_schema, str):
                schema_dict = json.loads(output_schema)

                if use_json_schema:
                    # Keep as dict schema for direct JSON output
                    kwargs["output_schema"] = schema_dict
                else:
                    # Convert to Pydantic model (default behavior)
                    dynamic_model = json_schema_to_pydantic_model(schema_dict)
                    kwargs["output_schema"] = dynamic_model
        except json.JSONDecodeError:
            kwargs.pop("output_schema")
            log_warning(f"Invalid output_schema JSON: {output_schema}")
        except Exception as e:
            kwargs.pop("output_schema")
            log_warning(f"Failed to create output_schema model: {e}")

    # Parse boolean and null values
    for key, value in kwargs.items():
        if isinstance(value, str) and value.lower() in ["true", "false"]:
            kwargs[key] = value.lower() == "true"
        elif isinstance(value, str) and value.lower() in ["null", "none"]:
            kwargs[key] = None

    return kwargs


def format_sse_event(event: Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]) -> str:
    """Parse JSON data into SSE-compliant format.

    Args:
        event_dict: Dictionary containing the event data

    Returns:
        SSE-formatted response:

        ```
        event: EventName
        data: { ... }

        event: AnotherEventName
        data: { ... }
        ```
    """
    try:
        # Parse the JSON to extract the event type
        event_type = event.event or "message"

        # Serialize to valid JSON with double quotes and no newlines
        clean_json = event.to_json(separators=(",", ":"), indent=None)

        return f"event: {event_type}\ndata: {clean_json}\n\n"
    except json.JSONDecodeError:
        clean_json = event.to_json(separators=(",", ":"), indent=None)
        return f"event: message\ndata: {clean_json}\n\n"


async def get_db(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb]]], db_id: Optional[str] = None, table: Optional[str] = None
) -> Union[BaseDb, AsyncBaseDb]:
    """Return the database with the given ID and/or table, or the first database if no ID/table is provided."""

    if table and not db_id:
        raise HTTPException(status_code=400, detail="The db_id query parameter is required when passing a table")

    async def _has_table(db: Union[BaseDb, AsyncBaseDb], table_name: str) -> bool:
        """Check if this database has the specified table (configured and actually exists)."""
        # First check if table name is configured
        is_configured = (
            hasattr(db, "session_table_name")
            and db.session_table_name == table_name
            or hasattr(db, "memory_table_name")
            and db.memory_table_name == table_name
            or hasattr(db, "metrics_table_name")
            and db.metrics_table_name == table_name
            or hasattr(db, "eval_table_name")
            and db.eval_table_name == table_name
            or hasattr(db, "knowledge_table_name")
            and db.knowledge_table_name == table_name
        )

        if not is_configured:
            return False

        # Then check if table actually exists in the database
        try:
            if isinstance(db, AsyncBaseDb):
                # For async databases, await the check
                return await db.table_exists(table_name)
            else:
                # For sync databases, call directly
                return db.table_exists(table_name)
        except (NotImplementedError, AttributeError):
            # If table_exists not implemented, fall back to configuration check
            return is_configured

    # If db_id is provided, first find the database with that ID
    if db_id:
        target_db_list = dbs.get(db_id)
        if not target_db_list:
            raise HTTPException(status_code=404, detail=f"No database found with id '{db_id}'")

        # If table is also specified, search through all databases with this ID to find one with the table
        if table:
            for db in target_db_list:
                if await _has_table(db, table):
                    return db
            raise HTTPException(status_code=404, detail=f"No database with id '{db_id}' has table '{table}'")

        # If no table specified, return the first database with this ID
        return target_db_list[0]

    # Raise if multiple databases are provided but no db_id is provided
    if len(dbs) > 1:
        raise HTTPException(
            status_code=400, detail="The db_id query parameter is required when using multiple databases"
        )

    # Return the first (and only) database
    return next(db for dbs in dbs.values() for db in dbs)


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

    runs = session.get("runs", []) or []
    session_type = session.get("session_type")

    # Handle workflows separately
    if session_type == "workflow":
        if not runs:
            return ""
        workflow_run = runs[0]
        workflow_input = workflow_run.get("input")
        if isinstance(workflow_input, str):
            return workflow_input
        elif isinstance(workflow_input, dict):
            try:
                return json.dumps(workflow_input)
            except (TypeError, ValueError):
                pass
        workflow_name = session.get("workflow_data", {}).get("name")
        return f"New {workflow_name} Session" if workflow_name else ""

    # For team, filter to team runs (runs without agent_id); for agents, use all runs
    if session_type == "team":
        runs_to_check = [r for r in runs if not r.get("agent_id")]
    else:
        runs_to_check = runs

    # Find the first user message across runs
    for r in runs_to_check:
        if r is None:
            continue
        run_dict = r if isinstance(r, dict) else r.to_dict()

        for message in run_dict.get("messages") or []:
            if message.get("role") == "user" and message.get("content"):
                return message["content"]

        run_input = r.get("input")
        if run_input is not None:
            return run_input.get("input_content")

    return ""


def extract_input_media(run_dict: Dict[str, Any]) -> Dict[str, Any]:
    input_media: Dict[str, List[Any]] = {
        "images": [],
        "videos": [],
        "audios": [],
        "files": [],
    }

    input = run_dict.get("input", {})
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


def format_team_tools(team_tools: List[Union[Function, dict]]):
    formatted_tools: List[Dict] = []
    if team_tools is not None:
        for tool in team_tools:
            if isinstance(tool, dict):
                formatted_tools.append(tool)
            elif isinstance(tool, Function):
                formatted_tools.append(tool.to_dict())
    return formatted_tools


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


#  INPUT SCHEMA VALIDATIONS


def get_agent_input_schema_dict(agent: Agent) -> Optional[Dict[str, Any]]:
    """Get input schema as dictionary for API responses"""

    if agent.input_schema is not None:
        try:
            return agent.input_schema.model_json_schema()
        except Exception:
            return None

    return None


def get_team_input_schema_dict(team: Team) -> Optional[Dict[str, Any]]:
    """Get input schema as dictionary for API responses"""

    if team.input_schema is not None:
        try:
            return team.input_schema.model_json_schema()
        except Exception:
            return None

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


def resolve_origins(user_origins: Optional[List[str]] = None, default_origins: Optional[List[str]] = None) -> List[str]:
    """
    Get CORS origins - user-provided origins override defaults.

    Args:
        user_origins: Optional list of user-provided CORS origins

    Returns:
        List of allowed CORS origins (user-provided if set, otherwise defaults)
    """
    # User-provided origins override defaults
    if user_origins:
        return user_origins

    # Default Agno domains
    return default_origins or [
        "http://localhost:3000",
        "https://agno.com",
        "https://www.agno.com",
        "https://app.agno.com",
        "https://os-stg.agno.com",
        "https://os.agno.com",
    ]


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
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if hasattr(type(tool), "__mro__") and any(
                c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
            ):
                if tool not in mcp_tools:
                    mcp_tools.append(tool)

    # Recursively check team members
    if team.members:
        for member in team.members:
            if isinstance(member, Agent):
                if member.tools:
                    for tool in member.tools:
                        # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
                        if hasattr(type(tool), "__mro__") and any(
                            c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
                        ):
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
                    # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
                    if hasattr(type(tool), "__mro__") and any(
                        c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
                    ):
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
                # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
                if hasattr(type(tool), "__mro__") and any(
                    c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
                ):
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


def _get_python_type_from_json_schema(field_schema: Dict[str, Any], field_name: str = "NestedModel") -> Type:
    """Map JSON schema type to Python type with recursive handling.

    Args:
        field_schema: JSON schema dictionary for a single field
        field_name: Name of the field (used for nested model naming)

    Returns:
        Python type corresponding to the JSON schema type
    """
    if not isinstance(field_schema, dict):
        return Any

    json_type = field_schema.get("type")

    # Handle basic types
    if json_type == "string":
        return str
    elif json_type == "integer":
        return int
    elif json_type == "number":
        return float
    elif json_type == "boolean":
        return bool
    elif json_type == "null":
        return type(None)
    elif json_type == "array":
        # Handle arrays with item type specification
        items_schema = field_schema.get("items")
        if items_schema and isinstance(items_schema, dict):
            item_type = _get_python_type_from_json_schema(items_schema, f"{field_name}Item")
            return List[item_type]  # type: ignore
        else:
            # No item type specified - use generic list
            return List[Any]
    elif json_type == "object":
        # Recursively create nested Pydantic model
        nested_properties = field_schema.get("properties", {})
        nested_required = field_schema.get("required", [])
        nested_title = field_schema.get("title", field_name)

        # Build field definitions for nested model
        nested_fields = {}
        for nested_field_name, nested_field_schema in nested_properties.items():
            nested_field_type = _get_python_type_from_json_schema(nested_field_schema, nested_field_name)

            if nested_field_name in nested_required:
                nested_fields[nested_field_name] = (nested_field_type, ...)
            else:
                nested_fields[nested_field_name] = (Optional[nested_field_type], None)  # type: ignore[assignment]

        # Create nested model if it has fields
        if nested_fields:
            return create_model(nested_title, **nested_fields)  # type: ignore
        else:
            # Empty object schema - use generic dict
            return Dict[str, Any]
    else:
        # Unknown or unspecified type - fallback to Any
        if json_type:
            logger.warning(f"Unknown JSON schema type '{json_type}' for field '{field_name}', using Any")
        return Any  # type: ignore


def json_schema_to_pydantic_model(schema: Dict[str, Any]) -> Type[BaseModel]:
    """Convert a JSON schema dictionary to a Pydantic BaseModel class.

    This function dynamically creates a Pydantic model from a JSON schema specification,
    handling nested objects, arrays, and optional fields.

    Args:
        schema: JSON schema dictionary with 'properties', 'required', 'type', etc.

    Returns:
        Dynamically created Pydantic BaseModel class
    """
    import copy

    # Deep copy to avoid modifying the original schema
    schema = copy.deepcopy(schema)

    # Extract schema components
    model_name = schema.get("title", "DynamicModel")
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    # Validate schema has properties
    if not properties:
        logger.warning(f"JSON schema '{model_name}' has no properties, creating empty model")

    # Build field definitions for create_model
    field_definitions = {}
    for field_name, field_schema in properties.items():
        try:
            field_type = _get_python_type_from_json_schema(field_schema, field_name)

            if field_name in required_fields:
                # Required field: (type, ...)
                field_definitions[field_name] = (field_type, ...)
            else:
                # Optional field: (Optional[type], None)
                field_definitions[field_name] = (Optional[field_type], None)  # type: ignore[assignment]
        except Exception as e:
            logger.warning(f"Failed to process field '{field_name}' in schema '{model_name}': {e}")
            # Skip problematic fields rather than failing entirely
            continue

    # Create and return the dynamic model
    try:
        return create_model(model_name, **field_definitions)  # type: ignore
    except Exception as e:
        logger.error(f"Failed to create dynamic model '{model_name}': {e}")
        # Return a minimal model as fallback
        return create_model(model_name)


def setup_tracing_for_os(db: Union[BaseDb, AsyncBaseDb]) -> None:
    """Set up OpenTelemetry tracing for this agent/team/workflow."""
    try:
        from agno.tracing import setup_tracing

        setup_tracing(db=db)
    except ImportError:
        logger.warning(
            "tracing=True but OpenTelemetry packages not installed. "
            "Install with: pip install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno"
        )
    except Exception as e:
        logger.warning(f"Failed to enable tracing: {e}")


def format_duration_ms(duration_ms: Optional[int]) -> str:
    """Format a duration in milliseconds to a human-readable string.

    Args:
        duration_ms: Duration in milliseconds

    Returns:
        Formatted string like "150ms" or "1.50s"
    """
    if duration_ms is None or duration_ms < 1000:
        return f"{duration_ms or 0}ms"
    return f"{duration_ms / 1000:.2f}s"


def parse_datetime_to_utc(datetime_str: str, param_name: str = "datetime") -> "datetime":
    """Parse an ISO 8601 datetime string and convert to UTC.

    Args:
        datetime_str: ISO 8601 formatted datetime string (e.g., '2025-11-19T10:00:00Z' or '2025-11-19T15:30:00+05:30')
        param_name: Name of the parameter for error messages

    Returns:
        datetime object in UTC timezone

    Raises:
        HTTPException: If the datetime string is invalid
    """
    try:
        dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
        # Convert to UTC if timezone-aware, otherwise assume UTC
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        else:
            return dt.replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name} format. Use ISO 8601 format (e.g., '2025-11-19T10:00:00Z' or '2025-11-19T10:00:00+05:30'): {e}",
        )
