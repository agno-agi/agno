"""Tool selection and resolution for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

from copy import copy, deepcopy
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from pydantic import BaseModel

from agno.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.team import (
    TeamRunOutput,
)
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
from agno.utils.team import (
    get_member_id,
    get_team_member_interactions_str,
    get_team_run_context_audio,
    get_team_run_context_files,
    get_team_run_context_images,
    get_team_run_context_videos,
)


async def _aresolve_callable_resources(team: "Team", run_context: "RunContext") -> None:
    """Resolve all callable factories (tools, knowledge, members) asynchronously."""
    from agno.utils.callables import aresolve_callable_knowledge, aresolve_callable_members, aresolve_callable_tools

    await aresolve_callable_tools(team, run_context)
    await aresolve_callable_knowledge(team, run_context)
    await aresolve_callable_members(team, run_context)


async def _check_and_refresh_mcp_tools(team: "Team") -> None:
    # Connect MCP tools
    from agno.team._init import _connect_mcp_tools

    await _connect_mcp_tools(
        team,
    )

    # Add provided tools - only if tools is a static list
    if team.tools is not None and isinstance(team.tools, list):
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
    from functools import partial

    from agno.team._default_tools import (
        _get_chat_history_function,
        _get_delegate_task_function,
        _get_previous_sessions_messages_function,
        _get_update_user_memory_function,
        _update_session_state_tool,
        create_knowledge_search_tool,
    )
    from agno.team._init import _connect_connectable_tools
    from agno.team._messages import _get_user_message
    from agno.utils.callables import (
        get_resolved_knowledge,
        get_resolved_members,
        get_resolved_tools,
        resolve_callable_knowledge,
        resolve_callable_members,
        resolve_callable_tools,
    )

    # In sync mode, resolve callable factories now
    if not async_mode:
        resolve_callable_tools(team, run_context)
        resolve_callable_knowledge(team, run_context)
        resolve_callable_members(team, run_context)

    resolved_tools = get_resolved_tools(team, run_context)
    resolved_knowledge = get_resolved_knowledge(team, run_context)
    resolved_members = get_resolved_members(team, run_context)

    _connect_connectable_tools(
        team,
    )

    # Prepare tools
    _tools: List[Union[Toolkit, Callable, Function, Dict]] = []

    # Add provided tools
    if resolved_tools is not None:
        for tool in resolved_tools:
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if hasattr(type(tool), "__mro__") and any(
                c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
            ):
                # Only add the tool if it successfully connected and built its tools
                if check_mcp_tools and not tool.initialized:  # type: ignore
                    continue
            _tools.append(tool)

    if team.read_chat_history:
        _tools.append(_get_chat_history_function(team, session=session, async_mode=async_mode))

    if team.memory_manager is not None and team.enable_agentic_memory:
        _tools.append(_get_update_user_memory_function(team, user_id=user_id, async_mode=async_mode))

    # Add learning machine tools
    if team._learning is not None:
        learning_tools = team._learning.get_tools(
            user_id=user_id,
            session_id=session.session_id if session else None,
            team_id=team.id,
        )
        _tools.extend(learning_tools)

    if team.enable_agentic_state:
        _tools.append(Function(name="update_session_state", entrypoint=partial(_update_session_state_tool, team)))

    if team.search_session_history:
        _tools.append(
            _get_previous_sessions_messages_function(
                team, num_history_sessions=team.num_history_sessions, user_id=user_id, async_mode=async_mode
            )
        )

    # Add tools for accessing knowledge
    # Single unified path through get_relevant_docs_from_knowledge(),
    # which checks knowledge_retriever first, then falls back to knowledge.search().
    if (resolved_knowledge is not None or team.knowledge_retriever is not None) and team.search_knowledge:
        _tools.append(
            create_knowledge_search_tool(
                team,
                run_response=run_response,
                run_context=run_context,
                knowledge_filters=run_context.knowledge_filters,
                enable_agentic_filters=team.enable_agentic_knowledge_filters,
                async_mode=async_mode,
            )
        )

    if resolved_knowledge is not None and team.update_knowledge:
        _tools.append(team.add_to_knowledge)

    from agno.team.mode import TeamMode

    if team.mode == TeamMode.tasks:
        # Tasks mode: provide task management tools instead of delegation tools
        from agno.team._task_tools import _get_task_management_tools
        from agno.team.task import load_task_list

        _task_list = load_task_list(run_context.session_state)
        task_tools = _get_task_management_tools(
            team=team,
            task_list=_task_list,
            run_response=run_response,
            run_context=run_context,
            session=session,
            team_run_context=team_run_context,
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
        _tools.extend(task_tools)
    elif resolved_members:
        # Get the user message if we are using the input directly
        user_message_content = None
        if team.determine_input_for_members is False:
            user_message = _get_user_message(
                team,
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

        delegate_task_func = _get_delegate_task_function(
            team,
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


def get_member_information(team: "Team", run_context: Optional["RunContext"] = None) -> str:
    """Get information about the members of the team, including their IDs, names, and roles."""
    return team.get_members_system_message_content(indent=0, run_context=run_context)


def _get_history_for_member_agent(
    team: "Team", session: TeamSession, member_agent: Union[Agent, "Team"]
) -> List[Message]:
    from agno.team.team import Team

    log_debug(f"Adding messages from history for {member_agent.name}")

    member_agent_id = member_agent.id if isinstance(member_agent, Agent) else None
    member_team_id = member_agent.id if isinstance(member_agent, Team) else None

    if not member_agent_id and not member_team_id:
        return []

    # Only skip messages from history when system_message_role is NOT a standard conversation role.
    # Standard conversation roles ("user", "assistant", "tool") should never be filtered
    # to preserve conversation continuity.
    skip_role = team.system_message_role if team.system_message_role not in ["user", "assistant", "tool"] else None

    history = session.get_messages(
        last_n_runs=member_agent.num_history_runs or team.num_history_runs,
        limit=member_agent.num_history_messages,
        skip_roles=[skip_role] if skip_role else None,
        member_ids=[member_agent_id] if member_agent_id else None,
        team_id=member_team_id,
    )

    if len(history) > 0:
        # Create a deep copy of the history messages to avoid modifying the original messages
        history_copy = [deepcopy(msg) for msg in history]

        # Tag each message as coming from history
        for _msg in history_copy:
            _msg.from_history = True

        return history_copy
    return []


def _determine_team_member_interactions(
    team: "Team",
    team_run_context: Dict[str, Any],
    images: List[Image],
    videos: List[Video],
    audio: List[Audio],
    files: List[File],
) -> Optional[str]:
    team_member_interactions_str = None
    if team.share_member_interactions:
        team_member_interactions_str = get_team_member_interactions_str(team_run_context=team_run_context)  # type: ignore
        if context_images := get_team_run_context_images(team_run_context=team_run_context):  # type: ignore
            images.extend(context_images)
        if context_videos := get_team_run_context_videos(team_run_context=team_run_context):  # type: ignore
            videos.extend(context_videos)
        if context_audio := get_team_run_context_audio(team_run_context=team_run_context):  # type: ignore
            audio.extend(context_audio)
        if context_files := get_team_run_context_files(team_run_context=team_run_context):  # type: ignore
            files.extend(context_files)
    return team_member_interactions_str


def _find_member_by_id(
    team: "Team", member_id: str, run_context: Optional["RunContext"] = None
) -> Optional[Tuple[int, Union[Agent, "Team"]]]:
    """Find a member (agent or team) by its URL-safe ID, searching recursively.

    Args:
        team: The team to search in.
        member_id (str): URL-safe ID of the member to find.
        run_context: Optional RunContext for resolving callable members.

    Returns:
        Optional[Tuple[int, Union[Agent, "Team"]]]: Tuple containing:
            - Index of the member in its immediate parent's members list
            - The matched member (Agent or Team)
    """
    from agno.team.team import Team
    from agno.utils.callables import get_resolved_members

    resolved_members = get_resolved_members(team, run_context)
    if resolved_members is None:
        return None

    # First check direct members
    for i, member in enumerate(resolved_members):
        url_safe_member_id = get_member_id(member)
        if url_safe_member_id == member_id:
            return i, member

        # If this member is a team, search its members recursively
        if isinstance(member, Team):
            result = member._find_member_by_id(member_id, run_context=run_context)
            if result is not None:
                return result

    return None


def _find_member_route_by_id(
    team: "Team", member_id: str, run_context: Optional[RunContext] = None
) -> Optional[Tuple[int, Union[Agent, "Team"]]]:
    """Find a routable member by ID for continue_run dispatching.

    For nested matches inside a sub-team, returns the top-level sub-team so callers
    can route through the sub-team's own continue_run path.

    Args:
        team: The team to search in.
        member_id (str): URL-safe ID of the member to find.
        run_context: Optional RunContext for resolving callable members.

    Returns:
        Optional[Tuple[int, Union[Agent, "Team"]]]: Tuple containing:
            - Index of the member in its immediate parent's members list
            - The direct member (or parent sub-team for nested matches)
    """
    from agno.team.team import Team
    from agno.utils.callables import get_resolved_members

    resolved_members = get_resolved_members(team, run_context)
    if resolved_members is None:
        return None
    for i, member in enumerate(resolved_members):
        url_safe_member_id = get_member_id(member)
        if url_safe_member_id == member_id:
            return i, member

        if isinstance(member, Team):
            result = member._find_member_by_id(member_id, run_context=run_context)
            if result is not None:
                return i, member

    return None


def _propagate_member_pause(
    run_response: TeamRunOutput,
    member_agent: Union[Agent, "Team"],
    member_run_response: Union[RunOutput, TeamRunOutput],
) -> None:
    """Copy HITL requirements from a paused member run to the team run response."""
    if not member_run_response.requirements:
        return
    if run_response.requirements is None:
        run_response.requirements = []
    member_id = get_member_id(member_agent)
    for req in member_run_response.requirements:
        req_copy = copy(req)
        # Deepcopy mutable fields to avoid shared state with the original
        if req_copy.tool_execution is not None:
            req_copy.tool_execution = deepcopy(req_copy.tool_execution)
        if req_copy.user_input_schema is not None:
            req_copy.user_input_schema = deepcopy(req_copy.user_input_schema)
        if req_copy.member_agent_id is None:
            req_copy.member_agent_id = member_id
        if req_copy.member_agent_name is None:
            req_copy.member_agent_name = member_agent.name
        if req_copy.member_run_id is None:
            req_copy.member_run_id = member_run_response.run_id
        # Keep a reference to the member's paused RunOutput so continue_run
        # can pass it directly without needing a session/DB lookup.
        req_copy._member_run_response = member_run_response
        run_response.requirements.append(req_copy)
