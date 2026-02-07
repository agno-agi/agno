"""Tool selection, built-in tools, and knowledge utilities for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

import asyncio
import contextlib
import json
from copy import copy, deepcopy
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)

from pydantic import BaseModel

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.filters import FilterExpr
from agno.knowledge.types import KnowledgeFilter
from agno.media import Audio, File, Image, Video
from agno.memory import MemoryManager
from agno.models.base import Model
from agno.models.message import Message, MessageReferences
from agno.run import RunContext
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.cancel import (
    acancel_run as acancel_run_global,
)
from agno.run.cancel import (
    cancel_run as cancel_run_global,
)
from agno.run.team import (
    TeamRunOutput,
    TeamRunOutputEvent,
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
from agno.utils.knowledge import get_agentic_or_user_search_filters
from agno.utils.log import (
    log_debug,
    log_info,
    log_warning,
    use_agent_logger,
    use_team_logger,
)
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.response import (
    check_if_run_cancelled,
)
from agno.utils.team import (
    add_interaction_to_team_run_context,
    format_member_agent_task,
    get_member_id,
    get_team_member_interactions_str,
    get_team_run_context_audio,
    get_team_run_context_files,
    get_team_run_context_images,
    get_team_run_context_videos,
)
from agno.utils.timer import Timer


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
    from agno.utils.callables import (
        get_resolved_knowledge,
        get_resolved_members,
        get_resolved_tools,
        resolve_callable_knowledge,
        resolve_callable_members,
        resolve_callable_tools,
    )

    # Resolve callable factories for tools, knowledge, and members
    resolve_callable_tools(team, run_context)
    resolve_callable_knowledge(team, run_context)
    resolve_callable_members(team, run_context)

    # Initialize members that were resolved from a callable factory
    resolved_members = get_resolved_members(team, run_context)
    if run_context.members is not None and resolved_members is not None:
        for member in resolved_members:
            team._initialize_member(member, debug_mode=team.debug_mode if hasattr(team, "debug_mode") else None)

    # Connect tools that require connection management
    team._connect_connectable_tools()

    # Prepare tools
    _tools: List[Union[Toolkit, Callable, Function, Dict]] = []

    # Add provided tools (resolved from factory or static)
    resolved_tools_list = get_resolved_tools(team, run_context)
    if resolved_tools_list is not None:
        for tool in resolved_tools_list:
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

    # Add learning machine tools
    if team._learning is not None:
        learning_tools = team._learning.get_tools(
            user_id=user_id,
            session_id=session.session_id if session else None,
            team_id=team.id,
        )
        _tools.extend(learning_tools)

    if team.enable_agentic_state:
        _tools.append(Function(name="update_session_state", entrypoint=team._update_session_state_tool))

    if team.search_session_history:
        _tools.append(
            team._get_previous_sessions_messages_function(
                num_history_sessions=team.num_history_sessions, user_id=user_id, async_mode=async_mode
            )
        )

    # Add tools for accessing knowledge (use resolved knowledge if available)
    resolved_knowledge = get_resolved_knowledge(team, run_context)
    if resolved_knowledge is not None and team.search_knowledge:
        # Use knowledge protocol's get_tools method
        _get_tools_fn = getattr(resolved_knowledge, "get_tools", None)
        if callable(_get_tools_fn):
            knowledge_tools = _get_tools_fn(
                run_response=run_response,
                run_context=run_context,
                knowledge_filters=run_context.knowledge_filters,
                async_mode=async_mode,
                enable_agentic_filters=team.enable_agentic_knowledge_filters,
                agent=team,
            )
            _tools.extend(knowledge_tools)

    if resolved_knowledge is not None and team.update_knowledge:
        _tools.append(team.add_to_knowledge)

    if team.members:
        from agno.team.mode import TeamMode

    # Use resolved members if available
    effective_members = (
        resolved_members if resolved_members is not None else (team.members if isinstance(team.members, list) else [])
    )

    if team.mode == TeamMode.tasks:
        # Tasks mode: provide task management tools regardless of whether members exist
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
    elif effective_members:
        # Standard modes: provide delegation tools
        effective_pass_user_input_to_members = team.effective_pass_user_input_to_members
        # Get the user message if we are using the input directly
        user_message_content = None
        if effective_pass_user_input_to_members:
            user_message = team._get_user_message(
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
        else:
            # Standard modes: provide delegation tools
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


def _get_update_user_memory_function(team: "Team", user_id: Optional[str] = None, async_mode: bool = False) -> Function:
    def update_user_memory(task: str) -> str:
        """
        Use this function to submit a task to modify the Agent's memory.
        Describe the task in detail and be specific.
        The task can include adding a memory, updating a memory, deleting a memory, or clearing all memories.

        Args:
            task: The task to update the memory. Be specific and describe the task in detail.

        Returns:
            str: A string indicating the status of the update.
        """
        team.memory_manager = cast(MemoryManager, team.memory_manager)
        response = team.memory_manager.update_memory_task(task=task, user_id=user_id)
        return response

    async def aupdate_user_memory(task: str) -> str:
        """
        Use this function to submit a task to modify the Agent's memory.
        Describe the task in detail and be specific.
        The task can include adding a memory, updating a memory, deleting a memory, or clearing all memories.

        Args:
            task: The task to update the memory. Be specific and describe the task in detail.

        Returns:
            str: A string indicating the status of the update.
        """
        team.memory_manager = cast(MemoryManager, team.memory_manager)
        response = await team.memory_manager.aupdate_memory_task(task=task, user_id=user_id)
        return response

    if async_mode:
        update_memory_function = aupdate_user_memory
    else:
        update_memory_function = update_user_memory  # type: ignore

    return Function.from_callable(update_memory_function, name="update_user_memory")


def get_member_information(team: "Team") -> str:
    """Get information about the members of the team, including their IDs, names, and roles."""
    return team.get_members_system_message_content(indent=0)


def _get_chat_history_function(team: "Team", session: TeamSession, async_mode: bool = False):
    def get_chat_history(num_chats: Optional[int] = None) -> str:
        """
        Use this function to get the team chat history in reverse chronological order.
        Leave the num_chats parameter blank to get the entire chat history.
        Example:
            - To get the last chat, use num_chats=1
            - To get the last 5 chats, use num_chats=5
            - To get all chats, leave num_chats blank

        Args:
            num_chats: The number of chats to return.
                Each chat contains 2 messages. One from the team and one from the user.
                Default: None

        Returns:
            str: A JSON string containing a list of dictionaries representing the team chat history.
        """
        import json

        history: List[Dict[str, Any]] = []

        all_chats = session.get_messages(team_id=team.id)

        if len(all_chats) == 0:
            return ""

        for chat in all_chats[::-1]:  # type: ignore
            history.insert(0, chat.to_dict())  # type: ignore

        if num_chats is not None:
            history = history[:num_chats]

        return json.dumps(history)

    async def aget_chat_history(num_chats: Optional[int] = None) -> str:
        """
        Use this function to get the team chat history in reverse chronological order.
        Leave the num_chats parameter blank to get the entire chat history.
        Example:
            - To get the last chat, use num_chats=1
            - To get the last 5 chats, use num_chats=5
            - To get all chats, leave num_chats blank

        Args:
            num_chats: The number of chats to return.
                Each chat contains 2 messages. One from the team and one from the user.
                Default: None

        Returns:
            str: A JSON string containing a list of dictionaries representing the team chat history.
        """
        import json

        history: List[Dict[str, Any]] = []

        all_chats = session.get_messages(team_id=team.id)

        if len(all_chats) == 0:
            return ""

        for chat in all_chats[::-1]:  # type: ignore
            history.insert(0, chat.to_dict())  # type: ignore

        if num_chats is not None:
            history = history[:num_chats]

        return json.dumps(history)

    if async_mode:
        get_chat_history_func = aget_chat_history
    else:
        get_chat_history_func = get_chat_history  # type: ignore
    return Function.from_callable(get_chat_history_func, name="get_chat_history")


def _update_session_state_tool(team: "Team", run_context: RunContext, session_state_updates: dict) -> str:
    """
    Update the shared session state.  Provide any updates as a dictionary of key-value pairs.
    Example:
        "session_state_updates": {"shopping_list": ["milk", "eggs", "bread"]}

    Args:
        session_state_updates (dict): The updates to apply to the shared session state. Should be a dictionary of key-value pairs.
    """
    if run_context.session_state is None:
        run_context.session_state = {}
    session_state = run_context.session_state
    for key, value in session_state_updates.items():
        session_state[key] = value

    return f"Updated session state: {session_state}"


def _get_previous_sessions_messages_function(
    team: "Team", num_history_sessions: Optional[int] = 2, user_id: Optional[str] = None, async_mode: bool = False
):
    """Factory function to create a get_previous_session_messages function.

    Args:
        num_history_sessions: The last n sessions to be taken from db
        user_id: The user ID to filter sessions by

    Returns:
        Callable: A function that retrieves messages from previous sessions
    """

    def get_previous_session_messages() -> str:
        """Use this function to retrieve messages from previous chat sessions.
        USE THIS TOOL ONLY WHEN THE QUESTION IS EITHER "What was my last conversation?" or "What was my last question?" and similar to it.

        Returns:
            str: JSON formatted list of message pairs from previous sessions
        """
        import json

        if team.db is None:
            return "Previous session messages not available"

        team.db = cast(BaseDb, team.db)
        selected_sessions = team.db.get_sessions(
            session_type=SessionType.TEAM,
            limit=num_history_sessions,
            user_id=user_id,
            sort_by="created_at",
            sort_order="desc",
        )

        all_messages = []
        seen_message_pairs = set()

        for session in selected_sessions:
            if isinstance(session, TeamSession) and session.runs:
                for run in session.runs:
                    messages = run.messages
                    if messages is not None:
                        for i in range(0, len(messages) - 1, 2):
                            if i + 1 < len(messages):
                                try:
                                    user_msg = messages[i]
                                    assistant_msg = messages[i + 1]
                                    user_content = user_msg.content
                                    assistant_content = assistant_msg.content
                                    if user_content is None or assistant_content is None:
                                        continue  # Skip this pair if either message has no content

                                    msg_pair_id = f"{user_content}:{assistant_content}"
                                    if msg_pair_id not in seen_message_pairs:
                                        seen_message_pairs.add(msg_pair_id)
                                        all_messages.append(Message.model_validate(user_msg))
                                        all_messages.append(Message.model_validate(assistant_msg))
                                except Exception as e:
                                    log_warning(f"Error processing message pair: {e}")
                                    continue

        return json.dumps([msg.to_dict() for msg in all_messages]) if all_messages else "No history found"

    async def aget_previous_session_messages() -> str:
        """Use this function to retrieve messages from previous chat sessions.
        USE THIS TOOL ONLY WHEN THE QUESTION IS EITHER "What was my last conversation?" or "What was my last question?" and similar to it.

        Returns:
            str: JSON formatted list of message pairs from previous sessions
        """
        import json

        if team.db is None:
            return "Previous session messages not available"

        if team._has_async_db():
            selected_sessions = await cast(AsyncBaseDb, team.db).get_sessions(  # type: ignore
                session_type=SessionType.TEAM,
                limit=num_history_sessions,
                user_id=user_id,
                sort_by="created_at",
                sort_order="desc",
            )
        else:
            selected_sessions = team.db.get_sessions(  # type: ignore
                session_type=SessionType.TEAM,
                limit=num_history_sessions,
                user_id=user_id,
                sort_by="created_at",
                sort_order="desc",
            )

        all_messages = []
        seen_message_pairs = set()

        for session in selected_sessions:
            if isinstance(session, TeamSession) and session.runs:
                for run in session.runs:
                    messages = run.messages
                    if messages is not None:
                        for i in range(0, len(messages) - 1, 2):
                            if i + 1 < len(messages):
                                try:
                                    user_msg = messages[i]
                                    assistant_msg = messages[i + 1]
                                    user_content = user_msg.content
                                    assistant_content = assistant_msg.content
                                    if user_content is None or assistant_content is None:
                                        continue  # Skip this pair if either message has no content

                                    msg_pair_id = f"{user_content}:{assistant_content}"
                                    if msg_pair_id not in seen_message_pairs:
                                        seen_message_pairs.add(msg_pair_id)
                                        all_messages.append(Message.model_validate(user_msg))
                                        all_messages.append(Message.model_validate(assistant_msg))
                                except Exception as e:
                                    log_warning(f"Error processing message pair: {e}")
                                    continue

        return json.dumps([msg.to_dict() for msg in all_messages]) if all_messages else "No history found"

    if team._has_async_db():
        return Function.from_callable(aget_previous_session_messages, name="get_previous_session_messages")
    else:
        return Function.from_callable(get_previous_session_messages, name="get_previous_session_messages")


def _get_history_for_member_agent(
    team: "Team", session: TeamSession, member_agent: Union[Agent, "Team"]
) -> List[Message]:
    from copy import deepcopy

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


def _find_member_by_id(team: "Team", member_id: str) -> Optional[Tuple[int, Union[Agent, "Team"]]]:
    """Find a member (agent or team) by its URL-safe ID, searching recursively.

    Returns the actual matched member, even if nested inside a sub-team.

    Args:
        team: The team to search in.
        member_id (str): URL-safe ID of the member to find.

    Returns:
        Optional[Tuple[int, Union[Agent, "Team"]]]: Tuple containing:
            - Index of the member in its immediate parent's members list
            - The matched member (Agent or Team)
    """
    from agno.team.team import Team

    # Use resolved members if available, otherwise fall back to static members
    members = team.members if isinstance(team.members, list) else []

    # First check direct members
    for i, member in enumerate(members):
        url_safe_member_id = get_member_id(member)
        if url_safe_member_id == member_id:
            return i, member

        # If this member is a team, search its members recursively
        if isinstance(member, Team):
            result = member._find_member_by_id(member_id)
            if result is not None:
                return result

    return None


def _find_member_route_by_id(team: "Team", member_id: str) -> Optional[Tuple[int, Union[Agent, "Team"]]]:
    """Find a routable member by ID for continue_run dispatching.

    For nested matches inside a sub-team, returns the top-level sub-team so callers
    can route through the sub-team's own continue_run path.

    Args:
        team: The team to search in.
        member_id (str): URL-safe ID of the member to find.

    Returns:
        Optional[Tuple[int, Union[Agent, "Team"]]]: Tuple containing:
            - Index of the member in its immediate parent's members list
            - The direct member (or parent sub-team for nested matches)
    """
    from agno.team.team import Team

    for i, member in enumerate(team.members):
        url_safe_member_id = get_member_id(member)
        if url_safe_member_id == member_id:
            return i, member

        if isinstance(member, Team):
            result = member._find_member_by_id(member_id)
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
        req_copy = deepcopy(req)
        if req_copy.member_agent_id is None:
            req_copy.member_agent_id = member_id
        if req_copy.member_agent_name is None:
            req_copy.member_agent_name = member_agent.name
        if req_copy.member_run_id is None:
            req_copy.member_run_id = member_run_response.run_id
        run_response.requirements.append(req_copy)


def _get_delegate_task_function(
    team: "Team",
    run_response: TeamRunOutput,
    run_context: RunContext,
    session: TeamSession,
    team_run_context: Dict[str, Any],
    user_id: Optional[str] = None,
    stream: bool = False,
    stream_events: bool = False,
    async_mode: bool = False,
    input: Optional[str] = None,  # Used when pass_user_input_to_members=True
    pass_user_input_to_members: Optional[bool] = None,
    images: Optional[List[Image]] = None,
    videos: Optional[List[Video]] = None,
    audio: Optional[List[Audio]] = None,
    files: Optional[List[File]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
) -> Function:
    if not images:
        images = []
    if not videos:
        videos = []
    if not audio:
        audio = []
    if not files:
        files = []
    effective_pass_user_input_to_members = (
        pass_user_input_to_members
        if pass_user_input_to_members is not None
        else team.effective_pass_user_input_to_members
    )

    def _setup_delegate_task_to_member(member_agent: Union[Agent, "Team"], task: str):
        # 1. Initialize the member agent
        team._initialize_member(member_agent)

        # If team has send_media_to_model=False, ensure member agent also has it set to False
        # This allows tools to access files while preventing models from receiving them
        if not team.send_media_to_model:
            member_agent.send_media_to_model = False

        # 2. Handle respond_directly nuances
        if team.respond_directly:
            # Since we return the response directly from the member agent, we need to set the output schema from the team down.
            # Get output_schema from run_context
            team_output_schema = run_context.output_schema if run_context else None
            if not member_agent.output_schema and team_output_schema:
                member_agent.output_schema = team_output_schema

            # If the member will produce structured output, we need to parse the response
            if member_agent.output_schema is not None:
                team._member_response_model = member_agent.output_schema

        # 3. Handle enable_agentic_knowledge_filters on the member agent
        if team.enable_agentic_knowledge_filters and not member_agent.enable_agentic_knowledge_filters:
            member_agent.enable_agentic_knowledge_filters = team.enable_agentic_knowledge_filters

        # 4. Determine team context to send
        team_member_interactions_str = team._determine_team_member_interactions(
            team_run_context, images=images, videos=videos, audio=audio, files=files
        )

        # 5. Get the team history
        team_history_str = None
        if team.add_team_history_to_members and session:
            team_history_str = session.get_team_history_context(num_runs=team.num_team_history_runs)

        # 6. Create the member agent task or use the input directly
        if effective_pass_user_input_to_members:
            member_agent_task = input  # type: ignore
        else:
            member_agent_task = task

        if team_history_str or team_member_interactions_str:
            member_agent_task = format_member_agent_task(  # type: ignore
                task_description=member_agent_task or "",
                team_member_interactions_str=team_member_interactions_str,
                team_history_str=team_history_str,
            )

        # 7. Add member-level history for the member if enabled (because we won't load the session for the member, so history won't be loaded automatically)
        history = None
        if hasattr(member_agent, "add_history_to_context") and member_agent.add_history_to_context:
            history = team._get_history_for_member_agent(session, member_agent)
            if history:
                if isinstance(member_agent_task, str):
                    history.append(Message(role="user", content=member_agent_task))

        return member_agent_task, history

    def _process_delegate_task_to_member(
        member_agent_run_response: Optional[Union[TeamRunOutput, RunOutput]],
        member_agent: Union[Agent, "Team"],
        member_agent_task: Union[str, Message],
        member_session_state_copy: Dict[str, Any],
    ):
        # Add team run id to the member run
        if member_agent_run_response is not None:
            member_agent_run_response.parent_run_id = run_response.run_id  # type: ignore

        # Update the top-level team run_response tool call to have the run_id of the member run
        if run_response.tools is not None and member_agent_run_response is not None:
            for tool in run_response.tools:
                if tool.tool_name and tool.tool_name.lower() == "delegate_task_to_member":
                    tool.child_run_id = member_agent_run_response.run_id  # type: ignore

        # Update the team run context
        member_name = member_agent.name if member_agent.name else member_agent.id if member_agent.id else "Unknown"
        if isinstance(member_agent_task, str):
            normalized_task = member_agent_task
        elif member_agent_task.content:
            normalized_task = str(member_agent_task.content)
        else:
            normalized_task = ""
        add_interaction_to_team_run_context(
            team_run_context=team_run_context,
            member_name=member_name,
            task=normalized_task,
            run_response=member_agent_run_response,  # type: ignore
        )

        # Add the member run to the team run response if enabled
        if run_response and member_agent_run_response:
            run_response.add_member_run(member_agent_run_response)

        # Scrub the member run based on that member's storage flags before storing
        if member_agent_run_response:
            if (
                not member_agent.store_media
                or not member_agent.store_tool_messages
                or not member_agent.store_history_messages
            ):
                member_agent._scrub_run_output_for_storage(member_agent_run_response)  # type: ignore

            # Add the member run to the team session
            session.upsert_run(member_agent_run_response)

        # Update team session state
        merge_dictionaries(run_context.session_state, member_session_state_copy)  # type: ignore

        # Update the team media
        if member_agent_run_response is not None:
            team._update_team_media(member_agent_run_response)  # type: ignore

    def delegate_task_to_member(member_id: str, task: str) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Use this function to delegate a task to the selected team member.
        You must provide a clear and concise description of the task the member should achieve AND the expected output.

        Args:
            member_id (str): The ID of the member to delegate the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.
            task (str): A clear and concise description of the task the member should achieve.
        Returns:
            str: The result of the delegated task.
        """

        # Find the member agent using the helper function
        result = team._find_member_by_id(member_id)
        if result is None:
            yield f"Member with ID {member_id} not found in the team or any subteams. Please choose the correct member from the list of members:\n\n{team.get_members_system_message_content(indent=0)}"
            return

        _, member_agent = result
        member_agent_task, history = _setup_delegate_task_to_member(member_agent=member_agent, task=task)

        # Make sure for the member agent, we are using the agent logger
        use_agent_logger()

        member_session_state_copy = copy(run_context.session_state)

        if stream:
            member_agent_run_response_stream = member_agent.run(
                input=member_agent_task if not history else history,
                user_id=user_id,
                # All members have the same session_id
                session_id=session.session_id,
                session_state=member_session_state_copy,  # Send a copy to the agent
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                stream=True,
                stream_events=stream_events or team.stream_member_events,
                debug_mode=debug_mode,
                dependencies=run_context.dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                metadata=run_context.metadata,
                add_session_state_to_context=add_session_state_to_context,
                knowledge_filters=run_context.knowledge_filters
                if not member_agent.knowledge_filters and member_agent.knowledge
                else None,
                yield_run_output=True,
            )
            member_agent_run_response = None
            for member_agent_run_output_event in member_agent_run_response_stream:
                # Do NOT break out of the loop, Iterator need to exit properly
                if isinstance(member_agent_run_output_event, (TeamRunOutput, RunOutput)):
                    member_agent_run_response = member_agent_run_output_event  # type: ignore
                    continue  # Don't yield TeamRunOutput or RunOutput, only yield events

                # Check if the run is cancelled
                check_if_run_cancelled(member_agent_run_output_event)

                # Yield the member event directly
                member_agent_run_output_event.parent_run_id = (
                    member_agent_run_output_event.parent_run_id or run_response.run_id
                )
                yield member_agent_run_output_event  # type: ignore
        else:
            member_agent_run_response = member_agent.run(  # type: ignore
                input=member_agent_task if not history else history,  # type: ignore
                user_id=user_id,
                # All members have the same session_id
                session_id=session.session_id,
                session_state=member_session_state_copy,  # Send a copy to the agent
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                stream=False,
                debug_mode=debug_mode,
                dependencies=run_context.dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=run_context.metadata,
                knowledge_filters=run_context.knowledge_filters
                if not member_agent.knowledge_filters and member_agent.knowledge
                else None,
            )

            check_if_run_cancelled(member_agent_run_response)  # type: ignore

        # Check if the member run is paused (HITL)
        if member_agent_run_response is not None and member_agent_run_response.is_paused:
            _propagate_member_pause(run_response, member_agent, member_agent_run_response)
            use_team_logger()
            _process_delegate_task_to_member(
                member_agent_run_response,
                member_agent,
                member_agent_task,  # type: ignore
                member_session_state_copy,  # type: ignore
            )
            yield f"Member '{member_agent.name}' requires human input before continuing."
            return

        if not stream:
            try:
                if member_agent_run_response.content is None and (  # type: ignore
                    member_agent_run_response.tools is None or len(member_agent_run_response.tools) == 0  # type: ignore
                ):
                    yield "No response from the member agent."
                elif isinstance(member_agent_run_response.content, str):  # type: ignore
                    content = member_agent_run_response.content.strip()  # type: ignore
                    if len(content) > 0:
                        yield content

                    # If the content is empty but we have tool calls
                    elif member_agent_run_response.tools is not None and len(member_agent_run_response.tools) > 0:  # type: ignore
                        tool_str = ""
                        for tool in member_agent_run_response.tools:  # type: ignore
                            if tool.result:
                                tool_str += f"{tool.result},"
                        yield tool_str.rstrip(",")

                elif issubclass(type(member_agent_run_response.content), BaseModel):  # type: ignore
                    yield member_agent_run_response.content.model_dump_json(indent=2)  # type: ignore
                else:
                    import json

                    yield json.dumps(member_agent_run_response.content, indent=2)  # type: ignore
            except Exception as e:
                yield str(e)

        # Afterward, switch back to the team logger
        use_team_logger()

        _process_delegate_task_to_member(
            member_agent_run_response,
            member_agent,
            member_agent_task,  # type: ignore
            member_session_state_copy,  # type: ignore
        )

    async def adelegate_task_to_member(
        member_id: str, task: str
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Use this function to delegate a task to the selected team member.
        You must provide a clear and concise description of the task the member should achieve AND the expected output.

        Args:
            member_id (str): The ID of the member to delegate the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.
            task (str): A clear and concise description of the task the member should achieve.
        Returns:
            str: The result of the delegated task.
        """

        # Find the member agent using the helper function
        result = team._find_member_by_id(member_id)
        if result is None:
            yield f"Member with ID {member_id} not found in the team or any subteams. Please choose the correct member from the list of members:\n\n{team.get_members_system_message_content(indent=0)}"
            return

        _, member_agent = result
        member_agent_task, history = _setup_delegate_task_to_member(member_agent=member_agent, task=task)

        # Make sure for the member agent, we are using the agent logger
        use_agent_logger()

        member_session_state_copy = copy(run_context.session_state)

        if stream:
            member_agent_run_response_stream = member_agent.arun(  # type: ignore
                input=member_agent_task if not history else history,
                user_id=user_id,
                # All members have the same session_id
                session_id=session.session_id,
                session_state=member_session_state_copy,  # Send a copy to the agent
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                stream=True,
                stream_events=stream_events or team.stream_member_events,
                debug_mode=debug_mode,
                dependencies=run_context.dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=run_context.metadata,
                knowledge_filters=run_context.knowledge_filters
                if not member_agent.knowledge_filters and member_agent.knowledge
                else None,
                yield_run_output=True,
            )
            member_agent_run_response = None
            async for member_agent_run_response_event in member_agent_run_response_stream:
                # Do NOT break out of the loop, AsyncIterator need to exit properly
                if isinstance(member_agent_run_response_event, (TeamRunOutput, RunOutput)):
                    member_agent_run_response = member_agent_run_response_event  # type: ignore
                    continue  # Don't yield TeamRunOutput or RunOutput, only yield events

                # Check if the run is cancelled
                check_if_run_cancelled(member_agent_run_response_event)

                # Yield the member event directly
                member_agent_run_response_event.parent_run_id = getattr(
                    member_agent_run_response_event, "parent_run_id", None
                ) or (run_response.run_id if run_response is not None else None)
                yield member_agent_run_response_event  # type: ignore
        else:
            member_agent_run_response = await member_agent.arun(  # type: ignore
                input=member_agent_task if not history else history,
                user_id=user_id,
                # All members have the same session_id
                session_id=session.session_id,
                session_state=member_session_state_copy,  # Send a copy to the agent
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                stream=False,
                debug_mode=debug_mode,
                dependencies=run_context.dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=run_context.metadata,
                knowledge_filters=run_context.knowledge_filters
                if not member_agent.knowledge_filters and member_agent.knowledge
                else None,
            )
            check_if_run_cancelled(member_agent_run_response)  # type: ignore

        # Check if the member run is paused (HITL)
        if member_agent_run_response is not None and member_agent_run_response.is_paused:
            _propagate_member_pause(run_response, member_agent, member_agent_run_response)
            use_team_logger()
            _process_delegate_task_to_member(
                member_agent_run_response,
                member_agent,
                member_agent_task,  # type: ignore
                member_session_state_copy,  # type: ignore
            )
            yield f"Member '{member_agent.name}' requires human input before continuing."
            return

        if not stream:
            try:
                if member_agent_run_response.content is None and (  # type: ignore
                    member_agent_run_response.tools is None or len(member_agent_run_response.tools) == 0  # type: ignore
                ):
                    yield "No response from the member agent."
                elif isinstance(member_agent_run_response.content, str):  # type: ignore
                    if len(member_agent_run_response.content.strip()) > 0:  # type: ignore
                        yield member_agent_run_response.content  # type: ignore

                    # If the content is empty but we have tool calls
                    elif (
                        member_agent_run_response.tools is not None  # type: ignore
                        and len(member_agent_run_response.tools) > 0  # type: ignore
                    ):
                        yield ",".join([tool.result for tool in member_agent_run_response.tools if tool.result])  # type: ignore
                elif issubclass(type(member_agent_run_response.content), BaseModel):  # type: ignore
                    yield member_agent_run_response.content.model_dump_json(indent=2)  # type: ignore
                else:
                    import json

                    yield json.dumps(member_agent_run_response.content, indent=2)  # type: ignore
            except Exception as e:
                yield str(e)

        # Afterward, switch back to the team logger
        use_team_logger()

        _process_delegate_task_to_member(
            member_agent_run_response,
            member_agent,
            member_agent_task,  # type: ignore
            member_session_state_copy,  # type: ignore
        )

    # When the task should be delegated to all members
    def delegate_task_to_members(task: str) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """
        Use this function to delegate a task to all the member agents and return a response.
        You must provide a clear and concise description of the task the member should achieve AND the expected output.

        Args:
            task (str): A clear and concise description of the task to send to member agents.
        Returns:
            str: The result of the delegated task.
        """

        # Run all the members sequentially
        _members = team.members if isinstance(team.members, list) else []
        for _, member_agent in enumerate(_members):
            member_agent_task, history = _setup_delegate_task_to_member(member_agent=member_agent, task=task)

            member_session_state_copy = copy(run_context.session_state)
            if stream:
                member_agent_run_response_stream = member_agent.run(
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    # All members have the same session_id
                    session_id=session.session_id,
                    session_state=member_session_state_copy,  # Send a copy to the agent
                    images=images,
                    videos=videos,
                    audio=audio,
                    files=files,
                    stream=True,
                    stream_events=stream_events or team.stream_member_events,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                    yield_run_output=True,
                )
                member_agent_run_response = None
                for member_agent_run_response_chunk in member_agent_run_response_stream:
                    # Do NOT break out of the loop, Iterator need to exit properly
                    if isinstance(member_agent_run_response_chunk, (TeamRunOutput, RunOutput)):
                        member_agent_run_response = member_agent_run_response_chunk  # type: ignore
                        continue  # Don't yield TeamRunOutput or RunOutput, only yield events

                    # Check if the run is cancelled
                    check_if_run_cancelled(member_agent_run_response_chunk)

                    # Yield the member event directly
                    member_agent_run_response_chunk.parent_run_id = member_agent_run_response_chunk.parent_run_id or (
                        run_response.run_id if run_response is not None else None
                    )
                    yield member_agent_run_response_chunk  # type: ignore

            else:
                member_agent_run_response = member_agent.run(  # type: ignore
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    # All members have the same session_id
                    session_id=session.session_id,
                    session_state=member_session_state_copy,  # Send a copy to the agent
                    images=images,
                    videos=videos,
                    audio=audio,
                    files=files,
                    stream=False,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                )

                check_if_run_cancelled(member_agent_run_response)  # type: ignore

            # Check if the member run is paused (HITL)
            if member_agent_run_response is not None and member_agent_run_response.is_paused:
                _propagate_member_pause(run_response, member_agent, member_agent_run_response)
                use_team_logger()
                _process_delegate_task_to_member(
                    member_agent_run_response,
                    member_agent,
                    member_agent_task,  # type: ignore
                    member_session_state_copy,  # type: ignore
                )
                yield f"Agent {member_agent.name}: Requires human input before continuing."
                continue

            if not stream:
                try:
                    if member_agent_run_response.content is None and (  # type: ignore
                        member_agent_run_response.tools is None or len(member_agent_run_response.tools) == 0  # type: ignore
                    ):
                        yield f"Agent {member_agent.name}: No response from the member agent."
                    elif isinstance(member_agent_run_response.content, str):  # type: ignore
                        if len(member_agent_run_response.content.strip()) > 0:  # type: ignore
                            yield f"Agent {member_agent.name}: {member_agent_run_response.content}"  # type: ignore
                        elif (
                            member_agent_run_response.tools is not None and len(member_agent_run_response.tools) > 0  # type: ignore
                        ):
                            yield f"Agent {member_agent.name}: {','.join([tool.result for tool in member_agent_run_response.tools])}"  # type: ignore
                    elif issubclass(type(member_agent_run_response.content), BaseModel):  # type: ignore
                        yield f"Agent {member_agent.name}: {member_agent_run_response.content.model_dump_json(indent=2)}"  # type: ignore
                    else:
                        import json

                        yield f"Agent {member_agent.name}: {json.dumps(member_agent_run_response.content, indent=2)}"  # type: ignore
                except Exception as e:
                    yield f"Agent {member_agent.name}: Error - {str(e)}"

            _process_delegate_task_to_member(
                member_agent_run_response,
                member_agent,
                member_agent_task,  # type: ignore
                member_session_state_copy,  # type: ignore
            )

        # After all the member runs, switch back to the team logger
        use_team_logger()

    # When the task should be delegated to all members
    async def adelegate_task_to_members(task: str) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Use this function to delegate a task to all the member agents and return a response.
        You must provide a clear and concise description of the task to send to member agents.

        Args:
            task (str): A clear and concise description of the task to send to member agents.
        Returns:
            str: The result of the delegated task.
        """

        if stream:
            # Concurrent streaming: launch each member as a streaming worker and merge events.
            # Safety note: _propagate_member_pause() and _process_delegate_task_to_member()
            # mutate shared run_response but each task runs in the same event loop, and mutations
            # only happen in the finally block after the stream is consumed, so there is no
            # concurrent mutation risk with asyncio cooperative scheduling.
            done_marker = object()
            queue: "asyncio.Queue[Union[RunOutputEvent, TeamRunOutputEvent, str, object]]" = asyncio.Queue()

            async def stream_member(agent: Union[Agent, "Team"]) -> None:
                member_agent_task, history = _setup_delegate_task_to_member(member_agent=agent, task=task)  # type: ignore
                member_session_state_copy = copy(run_context.session_state)

                try:
                    member_stream = agent.arun(  # type: ignore
                        input=member_agent_task if not history else history,
                        user_id=user_id,
                        session_id=session.session_id,
                        session_state=member_session_state_copy,  # Send a copy to the agent
                        images=images,
                        videos=videos,
                        audio=audio,
                        files=files,
                        stream=True,
                        stream_events=stream_events or team.stream_member_events,
                        debug_mode=debug_mode,
                        knowledge_filters=run_context.knowledge_filters
                        if not agent.knowledge_filters and agent.knowledge
                        else None,
                        dependencies=run_context.dependencies,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        metadata=run_context.metadata,
                        yield_run_output=True,
                    )
                    member_agent_run_response = None
                    try:
                        async for member_agent_run_output_event in member_stream:
                            # Do NOT break out of the loop, AsyncIterator need to exit properly
                            if isinstance(member_agent_run_output_event, (TeamRunOutput, RunOutput)):
                                member_agent_run_response = member_agent_run_output_event  # type: ignore
                                continue  # Don't yield TeamRunOutput or RunOutput, only yield events

                            check_if_run_cancelled(member_agent_run_output_event)
                            member_agent_run_output_event.parent_run_id = (
                                member_agent_run_output_event.parent_run_id
                                or (run_response.run_id if run_response is not None else None)
                            )
                            await queue.put(member_agent_run_output_event)
                    finally:
                        # Check if the member run is paused (HITL)
                        if member_agent_run_response is not None and member_agent_run_response.is_paused:
                            _propagate_member_pause(run_response, agent, member_agent_run_response)
                            _process_delegate_task_to_member(
                                member_agent_run_response,
                                agent,
                                member_agent_task,  # type: ignore
                                member_session_state_copy,  # type: ignore
                            )
                            await queue.put(f"Agent {agent.name}: Requires human input before continuing.")
                        else:
                            _process_delegate_task_to_member(
                                member_agent_run_response,
                                agent,
                                member_agent_task,  # type: ignore
                                member_session_state_copy,  # type: ignore
                            )
                finally:
                    # Always signal completion so the queue drain loop never deadlocks
                    await queue.put(done_marker)

            # Initialize and launch all members
            tasks: List[asyncio.Task[None]] = []
            _members = team.members if isinstance(team.members, list) else []
            for member_agent in _members:
                current_agent = member_agent
                team._initialize_member(current_agent)
                tasks.append(asyncio.create_task(stream_member(current_agent)))

            # Drain queue until all members reported done
            completed = 0
            try:
                while completed < len(tasks):
                    item = await queue.get()
                    if item is done_marker:
                        completed += 1
                    else:
                        yield item  # type: ignore
            finally:
                # Ensure tasks do not leak on cancellation
                for t in tasks:
                    if not t.done():
                        t.cancel()
                for t in tasks:
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await t

            # After draining, check for task exceptions that were raised
            # inside stream_member (after done_marker was sent)
            for t in tasks:
                if t.done() and not t.cancelled() and t.exception() is not None:
                    raise t.exception()  # type: ignore[misc]
        else:
            # Non-streaming concurrent run of members; collect results when done
            tasks = []
            _members = team.members if isinstance(team.members, list) else []
            for member_agent_index, member_agent in enumerate(_members):
                current_agent = member_agent
                member_agent_task, history = _setup_delegate_task_to_member(member_agent=current_agent, task=task)

                async def run_member_agent(
                    member_agent=current_agent,
                    member_agent_task=member_agent_task,
                    history=history,
                    member_agent_index=member_agent_index,
                ) -> Tuple[str, Optional[Union[Agent, "Team"]], Optional[Union[RunOutput, TeamRunOutput]]]:
                    member_session_state_copy = copy(run_context.session_state)

                    member_agent_run_response = await member_agent.arun(
                        input=member_agent_task if not history else history,
                        user_id=user_id,
                        # All members have the same session_id
                        session_id=session.session_id,
                        session_state=member_session_state_copy,  # Send a copy to the agent
                        images=images,
                        videos=videos,
                        audio=audio,
                        files=files,
                        stream=False,
                        stream_events=stream_events,
                        debug_mode=debug_mode,
                        knowledge_filters=run_context.knowledge_filters
                        if not member_agent.knowledge_filters and member_agent.knowledge
                        else None,
                        dependencies=run_context.dependencies,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        metadata=run_context.metadata,
                    )
                    check_if_run_cancelled(member_agent_run_response)

                    member_name = member_agent.name if member_agent.name else f"agent_{member_agent_index}"

                    # Check for pause BEFORE processing results so we don't lose pause state
                    if member_agent_run_response is not None and member_agent_run_response.is_paused:
                        _process_delegate_task_to_member(
                            member_agent_run_response,
                            member_agent,
                            member_agent_task,  # type: ignore
                            member_session_state_copy,  # type: ignore
                        )
                        return (
                            f"Agent {member_name}: Requires human input before continuing.",
                            member_agent,
                            member_agent_run_response,
                        )

                    _process_delegate_task_to_member(
                        member_agent_run_response,
                        member_agent,
                        member_agent_task,  # type: ignore
                        member_session_state_copy,  # type: ignore
                    )

                    result_text: str
                    try:
                        if member_agent_run_response.content is None and (
                            member_agent_run_response.tools is None or len(member_agent_run_response.tools) == 0
                        ):
                            result_text = f"Agent {member_name}: No response from the member agent."
                        elif isinstance(member_agent_run_response.content, str):
                            if len(member_agent_run_response.content.strip()) > 0:
                                result_text = f"Agent {member_name}: {member_agent_run_response.content}"
                            elif (
                                member_agent_run_response.tools is not None and len(member_agent_run_response.tools) > 0
                            ):
                                result_text = f"Agent {member_name}: {','.join([tool.result for tool in member_agent_run_response.tools])}"
                            else:
                                result_text = f"Agent {member_name}: No Response"
                        elif issubclass(type(member_agent_run_response.content), BaseModel):
                            result_text = (
                                f"Agent {member_name}: {member_agent_run_response.content.model_dump_json(indent=2)}"  # type: ignore
                            )
                        else:
                            import json

                            result_text = (
                                f"Agent {member_name}: {json.dumps(member_agent_run_response.content, indent=2)}"
                            )
                    except Exception as e:
                        result_text = f"Agent {member_name}: Error - {str(e)}"

                    return (result_text, None, None)

                tasks.append(run_member_agent)  # type: ignore

            gathered = await asyncio.gather(*[task() for task in tasks])  # type: ignore
            # Propagate HITL pauses sequentially after all coroutines complete
            for result_text, paused_agent, paused_response in gathered:
                if paused_agent is not None and paused_response is not None:
                    _propagate_member_pause(run_response, paused_agent, paused_response)
                yield result_text

        # After all the member runs, switch back to the team logger
        use_team_logger()

    if team.delegate_to_all_members:
        if async_mode:
            delegate_function = adelegate_task_to_members  # type: ignore
        else:
            delegate_function = delegate_task_to_members  # type: ignore

        delegate_func = Function.from_callable(delegate_function, name="delegate_task_to_members")
    else:
        if async_mode:
            delegate_function = adelegate_task_to_member  # type: ignore
        else:
            delegate_function = delegate_task_to_member  # type: ignore

        delegate_func = Function.from_callable(delegate_function, name="delegate_task_to_member")

    if team.respond_directly:
        delegate_func.stop_after_tool_call = True
        delegate_func.show_result = True

    return delegate_func


def add_to_knowledge(team: "Team", query: str, result: str) -> str:
    """Use this function to add information to the knowledge base for future use.

    Args:
        query (str): The query or topic to add.
        result (str): The actual content or information to store.

    Returns:
        str: A string indicating the status of the addition.
    """
    if team.knowledge is None:
        log_warning("Knowledge is not set, cannot add to knowledge")
        return "Knowledge is not set, cannot add to knowledge"

    insert_method = getattr(team.knowledge, "insert", None)
    if not callable(insert_method):
        log_warning("Knowledge base does not support adding content")
        return "Knowledge base does not support adding content"

    document_name = query.replace(" ", "_").replace("?", "").replace("!", "").replace(".", "")
    document_content = json.dumps({"query": query, "result": result})
    log_info(f"Adding document to Knowledge: {document_name}: {document_content}")
    from agno.knowledge.reader.text_reader import TextReader

    insert_method(name=document_name, text_content=document_content, reader=TextReader())
    return "Successfully added to knowledge base"


def get_relevant_docs_from_knowledge(
    team: "Team",
    query: str,
    num_documents: Optional[int] = None,
    filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    run_context: Optional[RunContext] = None,
    **kwargs,
) -> Optional[List[Union[Dict[str, Any], str]]]:
    """Return a list of references from the knowledge base"""
    from agno.knowledge.document import Document

    # Extract dependencies from run_context if available
    dependencies = run_context.dependencies if run_context else None

    if num_documents is None and team.knowledge is not None:
        num_documents = getattr(team.knowledge, "max_results", None)

    # Validate the filters against known valid filter keys
    if team.knowledge is not None and filters is not None:
        validate_filters_method = getattr(team.knowledge, "validate_filters", None)
        if callable(validate_filters_method):
            valid_filters, invalid_keys = validate_filters_method(filters)

            # Warn about invalid filter keys
            if invalid_keys:
                log_warning(f"Invalid filter keys provided: {invalid_keys}. These filters will be ignored.")

                # Only use valid filters
                filters = valid_filters
                if not filters:
                    log_warning("No valid filters remain after validation. Search will proceed without filters.")

            if invalid_keys == [] and valid_filters == {}:
                log_debug("No valid filters provided. Search will proceed without filters.")
                filters = None

    if team.knowledge_retriever is not None and callable(team.knowledge_retriever):
        from inspect import signature

        try:
            sig = signature(team.knowledge_retriever)
            knowledge_retriever_kwargs: Dict[str, Any] = {}
            if "team" in sig.parameters:
                knowledge_retriever_kwargs = {"team": team}
            if "filters" in sig.parameters:
                knowledge_retriever_kwargs["filters"] = filters
            if "run_context" in sig.parameters:
                knowledge_retriever_kwargs["run_context"] = run_context
            elif "dependencies" in sig.parameters:
                # Backward compatibility: support dependencies parameter
                knowledge_retriever_kwargs["dependencies"] = dependencies
            knowledge_retriever_kwargs.update({"query": query, "num_documents": num_documents, **kwargs})
            return team.knowledge_retriever(**knowledge_retriever_kwargs)
        except Exception as e:
            log_warning(f"Knowledge retriever failed: {e}")
            raise e
    # Use knowledge protocol's retrieve method
    try:
        if team.knowledge is None:
            return None

        # Use protocol retrieve() method if available
        retrieve_fn = getattr(team.knowledge, "retrieve", None)
        if not callable(retrieve_fn):
            log_debug("Knowledge does not implement retrieve()")
            return None

        if num_documents is None:
            num_documents = getattr(team.knowledge, "max_results", 10)

        log_debug(f"Retrieving from knowledge base with filters: {filters}")
        relevant_docs: List[Document] = retrieve_fn(query=query, max_results=num_documents, filters=filters)

        if not relevant_docs or len(relevant_docs) == 0:
            log_debug("No relevant documents found for query")
            return None

        return [doc.to_dict() for doc in relevant_docs]
    except Exception as e:
        log_warning(f"Error retrieving from knowledge base: {e}")
        raise e


async def aget_relevant_docs_from_knowledge(
    team: "Team",
    query: str,
    num_documents: Optional[int] = None,
    filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    run_context: Optional[RunContext] = None,
    **kwargs,
) -> Optional[List[Union[Dict[str, Any], str]]]:
    """Get relevant documents from knowledge base asynchronously."""
    from agno.knowledge.document import Document

    # Extract dependencies from run_context if available
    dependencies = run_context.dependencies if run_context else None

    if num_documents is None and team.knowledge is not None:
        num_documents = getattr(team.knowledge, "max_results", None)

    # Validate the filters against known valid filter keys
    if team.knowledge is not None and filters is not None:
        avalidate_filters_method = getattr(team.knowledge, "avalidate_filters", None)
        if callable(avalidate_filters_method):
            valid_filters, invalid_keys = await avalidate_filters_method(filters)

            # Warn about invalid filter keys
            if invalid_keys:
                log_warning(f"Invalid filter keys provided: {invalid_keys}. These filters will be ignored.")

                # Only use valid filters
                filters = valid_filters
                if not filters:
                    log_warning("No valid filters remain after validation. Search will proceed without filters.")

            if invalid_keys == [] and valid_filters == {}:
                log_debug("No valid filters provided. Search will proceed without filters.")
                filters = None

    if team.knowledge_retriever is not None and callable(team.knowledge_retriever):
        from inspect import isawaitable, signature

        try:
            sig = signature(team.knowledge_retriever)
            knowledge_retriever_kwargs: Dict[str, Any] = {}
            if "team" in sig.parameters:
                knowledge_retriever_kwargs = {"team": team}
            if "filters" in sig.parameters:
                knowledge_retriever_kwargs["filters"] = filters
            if "run_context" in sig.parameters:
                knowledge_retriever_kwargs["run_context"] = run_context
            elif "dependencies" in sig.parameters:
                # Backward compatibility: support dependencies parameter
                knowledge_retriever_kwargs["dependencies"] = dependencies
            knowledge_retriever_kwargs.update({"query": query, "num_documents": num_documents, **kwargs})

            result = team.knowledge_retriever(**knowledge_retriever_kwargs)

            if isawaitable(result):
                result = await result

            return result
        except Exception as e:
            log_warning(f"Knowledge retriever failed: {e}")
            raise e

    # Use knowledge protocol's retrieve method
    try:
        if team.knowledge is None:
            return None

        # Use protocol aretrieve() or retrieve() method if available
        aretrieve_fn = getattr(team.knowledge, "aretrieve", None)
        retrieve_fn = getattr(team.knowledge, "retrieve", None)

        if not callable(aretrieve_fn) and not callable(retrieve_fn):
            log_debug("Knowledge does not implement retrieve()")
            return None

        if num_documents is None:
            num_documents = getattr(team.knowledge, "max_results", 10)

        log_debug(f"Retrieving from knowledge base with filters: {filters}")

        if callable(aretrieve_fn):
            relevant_docs: List[Document] = await aretrieve_fn(query=query, max_results=num_documents, filters=filters)
        elif callable(retrieve_fn):
            relevant_docs = retrieve_fn(query=query, max_results=num_documents, filters=filters)
        else:
            return None

        if not relevant_docs or len(relevant_docs) == 0:
            log_debug("No relevant documents found for query")
            return None

        return [doc.to_dict() for doc in relevant_docs]
    except Exception as e:
        log_warning(f"Error retrieving from knowledge base: {e}")
        raise e


def _convert_documents_to_string(team: "Team", docs: List[Union[Dict[str, Any], str]]) -> str:
    if docs is None or len(docs) == 0:
        return ""

    if team.references_format == "yaml":
        import yaml

        return yaml.dump(docs)

    import json

    return json.dumps(docs, indent=2)


def _get_effective_filters(
    team: "Team", knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
) -> Optional[Any]:
    """
    Determine effective filters for the team, considering:
    1. Team-level filters (team.knowledge_filters)
    2. Run-time filters (knowledge_filters)

    Priority: Run-time filters > Team filters
    """
    effective_filters = None

    # Start with team-level filters if they exist
    if team.knowledge_filters:
        effective_filters = team.knowledge_filters.copy()

    # Apply run-time filters if they exist
    if knowledge_filters:
        if effective_filters:
            if isinstance(effective_filters, dict):
                if isinstance(knowledge_filters, dict):
                    effective_filters.update(cast(Dict[str, Any], knowledge_filters))
                else:
                    # If knowledge_filters is not a dict (e.g., list of FilterExpr), combine as list if effective_filters is dict
                    # Convert the dict to a list and concatenate
                    effective_filters = cast(Any, [effective_filters, *knowledge_filters])
            else:
                effective_filters = [*effective_filters, *knowledge_filters]
        else:
            effective_filters = knowledge_filters

    return effective_filters


def _get_search_knowledge_base_function(
    team: "Team",
    run_response: TeamRunOutput,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    async_mode: bool = False,
    run_context: Optional[RunContext] = None,
) -> Function:
    """Factory function to create a search_knowledge_base function with filters."""

    def search_knowledge_base(query: str) -> str:
        """Use this function to search the knowledge base for information about a query.

        Args:
            query: The query to search for.

        Returns:
            str: A string containing the response from the knowledge base.
        """
        # Get the relevant documents from the knowledge base, passing filters
        retrieval_timer = Timer()
        retrieval_timer.start()
        docs_from_knowledge = team.get_relevant_docs_from_knowledge(
            query=query, filters=knowledge_filters, run_context=run_context
        )
        if docs_from_knowledge is not None:
            references = MessageReferences(
                query=query, references=docs_from_knowledge, time=round(retrieval_timer.elapsed, 4)
            )
            # Add the references to the run_response
            if run_response.references is None:
                run_response.references = []
            run_response.references.append(references)
        retrieval_timer.stop()
        log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

        if docs_from_knowledge is None:
            return "No documents found"
        return team._convert_documents_to_string(docs_from_knowledge)

    async def asearch_knowledge_base(query: str) -> str:
        """Use this function to search the knowledge base for information about a query asynchronously.

        Args:
            query: The query to search for.

        Returns:
            str: A string containing the response from the knowledge base.
        """
        retrieval_timer = Timer()
        retrieval_timer.start()
        docs_from_knowledge = await team.aget_relevant_docs_from_knowledge(
            query=query, filters=knowledge_filters, run_context=run_context
        )
        if docs_from_knowledge is not None:
            references = MessageReferences(
                query=query, references=docs_from_knowledge, time=round(retrieval_timer.elapsed, 4)
            )
            if run_response.references is None:
                run_response.references = []
            run_response.references.append(references)
        retrieval_timer.stop()
        log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

        if docs_from_knowledge is None:
            return "No documents found"
        return team._convert_documents_to_string(docs_from_knowledge)

    if async_mode:
        search_knowledge_base_function = asearch_knowledge_base
    else:
        search_knowledge_base_function = search_knowledge_base  # type: ignore

    return Function.from_callable(search_knowledge_base_function, name="search_knowledge_base")


def _get_search_knowledge_base_with_agentic_filters_function(
    team: "Team",
    run_response: TeamRunOutput,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    async_mode: bool = False,
    run_context: Optional[RunContext] = None,
) -> Function:
    """Factory function to create a search_knowledge_base function with filters."""

    def search_knowledge_base(query: str, filters: Optional[List[KnowledgeFilter]] = None) -> str:
        """Use this function to search the knowledge base for information about a query.

        Args:
            query: The query to search for.
            filters (optional): The filters to apply to the search. This is a list of KnowledgeFilter objects.

        Returns:
            str: A string containing the response from the knowledge base.
        """
        filters_dict = {filt.key: filt.value for filt in filters} if filters else None
        search_filters = get_agentic_or_user_search_filters(filters_dict, knowledge_filters)

        # Get the relevant documents from the knowledge base, passing filters
        retrieval_timer = Timer()
        retrieval_timer.start()
        docs_from_knowledge = team.get_relevant_docs_from_knowledge(
            query=query, filters=search_filters, run_context=run_context
        )
        if docs_from_knowledge is not None:
            references = MessageReferences(
                query=query, references=docs_from_knowledge, time=round(retrieval_timer.elapsed, 4)
            )
            # Add the references to the run_response
            if run_response.references is None:
                run_response.references = []
            run_response.references.append(references)
        retrieval_timer.stop()
        log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

        if docs_from_knowledge is None:
            return "No documents found"
        return team._convert_documents_to_string(docs_from_knowledge)

    async def asearch_knowledge_base(query: str, filters: Optional[List[KnowledgeFilter]] = None) -> str:
        """Use this function to search the knowledge base for information about a query asynchronously.

        Args:
            query: The query to search for.
            filters (optional): The filters to apply to the search. This is a list of KnowledgeFilter objects.

        Returns:
            str: A string containing the response from the knowledge base.
        """
        filters_dict = {filt.key: filt.value for filt in filters} if filters else None
        search_filters = get_agentic_or_user_search_filters(filters_dict, knowledge_filters)

        retrieval_timer = Timer()
        retrieval_timer.start()
        docs_from_knowledge = await team.aget_relevant_docs_from_knowledge(
            query=query, filters=search_filters, run_context=run_context
        )
        if docs_from_knowledge is not None:
            references = MessageReferences(
                query=query, references=docs_from_knowledge, time=round(retrieval_timer.elapsed, 4)
            )
            if run_response.references is None:
                run_response.references = []
            run_response.references.append(references)
        retrieval_timer.stop()
        log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

        if docs_from_knowledge is None:
            return "No documents found"
        return team._convert_documents_to_string(docs_from_knowledge)

    if async_mode:
        search_knowledge_base_function = asearch_knowledge_base
    else:
        search_knowledge_base_function = search_knowledge_base  # type: ignore

    return Function.from_callable(search_knowledge_base_function, name="search_knowledge_base")
