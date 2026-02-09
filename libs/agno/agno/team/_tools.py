"""Tool selection and infrastructure for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.run import RunContext
from agno.run.cancel import (
    acancel_run as acancel_run_global,
)
from agno.run.cancel import (
    cancel_run as cancel_run_global,
)
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.agent import (
    collect_joint_audios,
    collect_joint_files,
    collect_joint_images,
    collect_joint_videos,
)
from agno.utils.log import (
    log_debug,
    log_warning,
)


def cancel_run(run_id: str) -> bool:
    """Cancel a running team execution.

    Args:
        run_id (str): The run_id to cancel.

    Returns:
        bool: True if the run was found and marked for cancellation, False otherwise.
    """
    return cancel_run_global(run_id)


async def acancel_run(run_id: str) -> bool:
    """Cancel a running team execution.

    Args:
        run_id (str): The run_id to cancel.

    Returns:
        bool: True if the run was found and marked for cancellation, False otherwise.
    """
    return await acancel_run_global(run_id)


def _resolve_run_dependencies(team: "Team", run_context: RunContext) -> None:
    from inspect import signature

    log_debug("Resolving dependencies")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Dependencies is not a dict")
        return

    for key, value in run_context.dependencies.items():
        if not callable(value):
            run_context.dependencies[key] = value
            continue

        try:
            sig = signature(value)

            # Build kwargs for the function
            kwargs: Dict[str, Any] = {}
            if "agent" in sig.parameters:
                kwargs["agent"] = team
            if "team" in sig.parameters:
                kwargs["team"] = team
            if "run_context" in sig.parameters:
                kwargs["run_context"] = run_context

            resolved_value = value(**kwargs) if kwargs else value()

            run_context.dependencies[key] = resolved_value
        except Exception as e:
            log_warning(f"Failed to resolve dependencies for {key}: {e}")


async def _aresolve_run_dependencies(team: "Team", run_context: RunContext) -> None:
    from inspect import iscoroutine, signature

    log_debug("Resolving context (async)")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Dependencies is not a dict")
        return

    for key, value in run_context.dependencies.items():
        if not callable(value):
            run_context.dependencies[key] = value
            continue

        try:
            sig = signature(value)

            # Build kwargs for the function
            kwargs: Dict[str, Any] = {}
            if "agent" in sig.parameters:
                kwargs["agent"] = team
            if "team" in sig.parameters:
                kwargs["team"] = team
            if "run_context" in sig.parameters:
                kwargs["run_context"] = run_context

            resolved_value = value(**kwargs) if kwargs else value()

            if iscoroutine(resolved_value):
                resolved_value = await resolved_value

            run_context.dependencies[key] = resolved_value
        except Exception as e:
            log_warning(f"Failed to resolve context for '{key}': {e}")


async def _check_and_refresh_mcp_tools(team: "Team") -> None:
    # Connect MCP tools
    await team._connect_mcp_tools()

    # Add provided tools
    if team.tools is not None:
        for tool in team.tools:
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if hasattr(type(tool), "__mro__") and any(
                c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
            ):
                if tool.refresh_connection:  # type: ignore
                    try:
                        is_alive = await tool.is_alive()  # type: ignore
                        if not is_alive:
                            await tool.connect(force=True)  # type: ignore
                    except (RuntimeError, BaseException) as e:
                        log_warning(f"Failed to check if MCP tool is alive: {e}")
                        continue

                    try:
                        await tool.build_tools()  # type: ignore
                    except (RuntimeError, BaseException) as e:
                        log_warning(f"Failed to build tools for {str(tool)}: {e}")
                        continue


def _determine_tools_for_model(
    team: "Team",
    model: Model,
    run_response: TeamRunOutput,
    run_context: RunContext,
    team_run_context: Dict[str, Any],
    session: TeamSession,
    user_id: Optional[str] = None,
    async_mode: bool = False,
    input_message: Optional[Union[str, List, Dict, Message, BaseModel, List[Message]]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    audio: Optional[Sequence[Audio]] = None,
    files: Optional[Sequence[File]] = None,
    debug_mode: Optional[bool] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = None,
    check_mcp_tools: bool = True,
) -> List[Union[Function, dict]]:
    # Connect tools that require connection management
    team._connect_connectable_tools()

    # Prepare tools
    _tools: List[Union[Toolkit, Callable, Function, Dict]] = []

    # Add provided tools
    if team.tools is not None:
        for tool in team.tools:
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if hasattr(type(tool), "__mro__") and any(
                c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
            ):
                # Only add the tool if it successfully connected and built its tools
                if check_mcp_tools and not tool.initialized:  # type: ignore
                    continue
            _tools.append(tool)

    if team.read_chat_history:
        _tools.append(team._get_chat_history_function(session=session, async_mode=async_mode))

    if team.memory_manager is not None and team.enable_agentic_memory:
        _tools.append(team._get_update_user_memory_function(user_id=user_id, async_mode=async_mode))

    if team.enable_agentic_state:
        _tools.append(Function(name="update_session_state", entrypoint=team._update_session_state_tool))

    if team.search_session_history:
        _tools.append(
            team._get_previous_sessions_messages_function(
                num_history_sessions=team.num_history_sessions, user_id=user_id, async_mode=async_mode
            )
        )

    # Add tools for accessing knowledge
    if team.knowledge is not None and team.search_knowledge:
        # Use knowledge protocol's get_tools method
        get_tools_fn = getattr(team.knowledge, "get_tools", None)
        if callable(get_tools_fn):
            knowledge_tools = get_tools_fn(
                run_response=run_response,
                run_context=run_context,
                knowledge_filters=run_context.knowledge_filters,
                async_mode=async_mode,
                enable_agentic_filters=team.enable_agentic_knowledge_filters,
                agent=team,
            )
            _tools.extend(knowledge_tools)

    if team.knowledge is not None and team.update_knowledge:
        _tools.append(team.add_to_knowledge)

    if team.members:
        # Get the user message if we are using the input directly
        user_message_content = None
        if team.determine_input_for_members is False:
            user_message = team._get_user_message(
                run_response=run_response,
                run_context=run_context,
                input_message=input_message,
                user_id=user_id,
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                add_dependencies_to_context=add_dependencies_to_context,
            )
            user_message_content = user_message.content if user_message is not None else None

        delegate_task_func = team._get_delegate_task_function(
            run_response=run_response,
            run_context=run_context,
            session=session,
            team_run_context=team_run_context,
            input=user_message_content,
            user_id=user_id,
            stream=stream or False,
            stream_events=stream_events or False,
            async_mode=async_mode,
            images=images,  # type: ignore
            videos=videos,  # type: ignore
            audio=audio,  # type: ignore
            files=files,  # type: ignore
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            debug_mode=debug_mode,
        )

        _tools.append(delegate_task_func)
        if team.get_member_information_tool:
            _tools.append(team.get_member_information)

    # Get Agent tools
    if len(_tools) > 0:
        log_debug("Processing tools for model")

    _function_names = []
    _functions: List[Union[Function, dict]] = []
    team._tool_instructions = []

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # Check if we need strict mode for the model
    strict = False
    if output_schema is not None and not team.use_json_mode and model.supports_native_structured_outputs:
        strict = True

    for tool in _tools:
        if isinstance(tool, Dict):
            # If a dict is passed, it is a builtin tool
            # that is run by the model provider and not the Agent
            _functions.append(tool)
            log_debug(f"Included builtin tool {tool}")

        elif isinstance(tool, Toolkit):
            # For each function in the toolkit and process entrypoint
            toolkit_functions = tool.get_async_functions() if async_mode else tool.get_functions()
            for name, _func in toolkit_functions.items():
                if name in _function_names:
                    continue
                _function_names.append(name)
                _func = _func.model_copy(deep=True)

                _func._team = team
                # Respect the function's explicit strict setting if set
                effective_strict = strict if _func.strict is None else _func.strict
                _func.process_entrypoint(strict=effective_strict)
                if strict and _func.strict is None:
                    _func.strict = True
                if team.tool_hooks:
                    _func.tool_hooks = team.tool_hooks
                _functions.append(_func)
                log_debug(f"Added tool {_func.name} from {tool.name}")

            # Add instructions from the toolkit
            if tool.add_instructions and tool.instructions is not None:
                if team._tool_instructions is None:
                    team._tool_instructions = []
                team._tool_instructions.append(tool.instructions)

        elif isinstance(tool, Function):
            if tool.name in _function_names:
                continue
            _function_names.append(tool.name)
            tool = tool.model_copy(deep=True)
            tool._team = team
            # Respect the function's explicit strict setting if set
            effective_strict = strict if tool.strict is None else tool.strict
            tool.process_entrypoint(strict=effective_strict)
            if strict and tool.strict is None:
                tool.strict = True
            if team.tool_hooks:
                tool.tool_hooks = team.tool_hooks
            _functions.append(tool)
            log_debug(f"Added tool {tool.name}")

            # Add instructions from the Function
            if tool.add_instructions and tool.instructions is not None:
                if team._tool_instructions is None:
                    team._tool_instructions = []
                team._tool_instructions.append(tool.instructions)

        elif callable(tool):
            # We add the tools, which are callable functions
            try:
                _func = Function.from_callable(tool, strict=strict)
                _func = _func.model_copy(deep=True)
                if _func.name in _function_names:
                    continue
                _function_names.append(_func.name)

                _func._team = team
                if strict:
                    _func.strict = True
                if team.tool_hooks:
                    _func.tool_hooks = team.tool_hooks
                _functions.append(_func)
                log_debug(f"Added tool {_func.name}")
            except Exception as e:
                log_warning(f"Could not add tool {tool}: {e}")

    if _functions:
        from inspect import signature

        # Check if any functions need media before collecting
        needs_media = any(
            any(param in signature(func.entrypoint).parameters for param in ["images", "videos", "audios", "files"])
            for func in _functions
            if isinstance(func, Function) and func.entrypoint is not None
        )

        # Only collect media if functions actually need them
        joint_images = collect_joint_images(run_response.input, session) if needs_media else None  # type: ignore
        joint_files = collect_joint_files(run_response.input) if needs_media else None  # type: ignore
        joint_audios = collect_joint_audios(run_response.input, session) if needs_media else None  # type: ignore
        joint_videos = collect_joint_videos(run_response.input, session) if needs_media else None  # type: ignore

        for func in _functions:  # type: ignore
            if isinstance(func, Function):
                func._run_context = run_context
                func._images = joint_images
                func._files = joint_files
                func._audios = joint_audios
                func._videos = joint_videos

    return _functions
