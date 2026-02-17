"""Tool resolution, formatting, and execution helpers for Agent."""

from __future__ import annotations

from collections import deque
from typing import (
    TYPE_CHECKING,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Union,
    cast,
)

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run import RunContext
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.messages import RunMessages
from agno.session import AgentSession
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.agent import (
    collect_joint_audios,
    collect_joint_files,
    collect_joint_images,
    collect_joint_videos,
)
from agno.utils.events import (
    create_tool_call_completed_event,
    create_tool_call_error_event,
    create_tool_call_started_event,
    handle_event,
)
from agno.utils.log import log_debug, log_warning


def raise_if_async_tools(agent: Agent) -> None:
    """Raise an exception if any tools contain async functions."""
    if agent.tools is None:
        return

    # Skip check if tools is a callable factory (not yet resolved)
    if not isinstance(agent.tools, list):
        return

    from inspect import iscoroutinefunction

    for tool in agent.tools:
        if isinstance(tool, Toolkit):
            for func in tool.functions:
                if iscoroutinefunction(tool.functions[func].entrypoint):
                    raise Exception(
                        f"Async tool {tool.name} can't be used with synchronous agent.run() or agent.print_response(). "
                        "Use agent.arun() or agent.aprint_response() instead to use this tool."
                    )
        elif isinstance(tool, Function):
            if iscoroutinefunction(tool.entrypoint):
                raise Exception(
                    f"Async function {tool.name} can't be used with synchronous agent.run() or agent.print_response(). "
                    "Use agent.arun() or agent.aprint_response() instead to use this tool."
                )
        elif callable(tool):
            if iscoroutinefunction(tool):
                raise Exception(
                    f"Async function {tool.__name__} can't be used with synchronous agent.run() or agent.print_response(). "
                    "Use agent.arun() or agent.aprint_response() instead to use this tool."
                )


def _raise_if_async_tools_in_list(tools: list) -> None:
    """Raise if any tools in a concrete list are async."""
    from inspect import iscoroutinefunction

    for tool in tools:
        if isinstance(tool, Toolkit):
            for func in tool.functions:
                if iscoroutinefunction(tool.functions[func].entrypoint):
                    raise Exception(
                        f"Async tool {tool.name} can't be used with synchronous agent.run() or agent.print_response(). "
                        "Use agent.arun() or agent.aprint_response() instead to use this tool."
                    )
        elif isinstance(tool, Function):
            if iscoroutinefunction(tool.entrypoint):
                raise Exception(
                    f"Async function {tool.name} can't be used with synchronous agent.run() or agent.print_response(). "
                    "Use agent.arun() or agent.aprint_response() instead to use this tool."
                )
        elif callable(tool):
            if iscoroutinefunction(tool):
                raise Exception(
                    f"Async function {tool.__name__} can't be used with synchronous agent.run() or agent.print_response(). "
                    "Use agent.arun() or agent.aprint_response() instead to use this tool."
                )


def get_tools(
    agent: Agent,
    run_response: RunOutput,
    run_context: RunContext,
    session: AgentSession,
    user_id: Optional[str] = None,
) -> List[Union[Toolkit, Callable, Function, Dict]]:
    from agno.agent import _default_tools, _init
    from agno.utils.callables import (
        get_resolved_knowledge,
        get_resolved_tools,
        resolve_callable_knowledge,
        resolve_callable_tools,
    )

    agent_tools: List[Union[Toolkit, Callable, Function, Dict]] = []

    # Resolve callable factories
    resolve_callable_tools(agent, run_context)
    resolve_callable_knowledge(agent, run_context)

    resolved_tools = get_resolved_tools(agent, run_context)
    resolved_knowledge = get_resolved_knowledge(agent, run_context)

    # Connect tools that require connection management
    _init.connect_connectable_tools(agent)

    # Add provided tools
    if resolved_tools is not None:
        # If not running in async mode, raise if any tool is async
        _raise_if_async_tools_in_list(resolved_tools)
        agent_tools.extend(resolved_tools)

    # Add tools for accessing memory
    if agent.read_chat_history:
        agent_tools.append(_default_tools.get_chat_history_function(agent, session=session))
    if agent.read_tool_call_history:
        agent_tools.append(_default_tools.get_tool_call_history_function(agent, session=session))
    if agent.search_session_history:
        agent_tools.append(
            _default_tools.get_previous_sessions_messages_function(
                agent, num_history_sessions=agent.num_history_sessions, user_id=user_id
            )
        )

    if agent.enable_agentic_memory:
        agent_tools.append(_default_tools.get_update_user_memory_function(agent, user_id=user_id, async_mode=False))

    # Add learning machine tools
    if agent._learning is not None:
        learning_tools = agent._learning.get_tools(
            user_id=user_id,
            session_id=session.session_id if session else None,
            agent_id=agent.id,
        )
        agent_tools.extend(learning_tools)

    if agent.enable_agentic_culture:
        agent_tools.append(_default_tools.get_update_cultural_knowledge_function(agent, async_mode=False))

    if agent.enable_agentic_state:
        agent_tools.append(
            Function(
                name="update_session_state",
                entrypoint=_default_tools.make_update_session_state_entrypoint(agent),
            )
        )

    # Add tools for accessing knowledge
    if resolved_knowledge is not None and agent.search_knowledge:
        # Use knowledge protocol's get_tools method
        get_tools_fn = getattr(resolved_knowledge, "get_tools", None)
        if callable(get_tools_fn):
            knowledge_tools = get_tools_fn(
                run_response=run_response,
                run_context=run_context,
                knowledge_filters=run_context.knowledge_filters,
                async_mode=False,
                enable_agentic_filters=agent.enable_agentic_knowledge_filters,
                agent=agent,
            )
            agent_tools.extend(knowledge_tools)
    elif agent.knowledge_retriever is not None and agent.search_knowledge:
        # Create search tool using custom knowledge_retriever
        agent_tools.append(
            _default_tools.create_knowledge_retriever_search_tool(
                agent,
                run_response=run_response,
                run_context=run_context,
                async_mode=False,
            )
        )

    if resolved_knowledge is not None and agent.update_knowledge:
        agent_tools.append(agent.add_to_knowledge)

    # Add tools for accessing skills
    if agent.skills is not None:
        agent_tools.extend(agent.skills.get_tools())

    return agent_tools


async def aget_tools(
    agent: Agent,
    run_response: RunOutput,
    run_context: RunContext,
    session: AgentSession,
    user_id: Optional[str] = None,
    check_mcp_tools: bool = True,
) -> List[Union[Toolkit, Callable, Function, Dict]]:
    from agno.agent import _default_tools, _init
    from agno.utils.callables import (
        aresolve_callable_knowledge,
        aresolve_callable_tools,
        get_resolved_knowledge,
        get_resolved_tools,
    )

    agent_tools: List[Union[Toolkit, Callable, Function, Dict]] = []

    # Resolve callable factories
    await aresolve_callable_tools(agent, run_context)
    await aresolve_callable_knowledge(agent, run_context)

    resolved_tools = get_resolved_tools(agent, run_context)
    resolved_knowledge = get_resolved_knowledge(agent, run_context)

    # Connect tools that require connection management
    _init.connect_connectable_tools(agent)

    # Connect MCP tools
    await _init.connect_mcp_tools(agent)

    # Add provided tools
    if resolved_tools is not None:
        for tool in resolved_tools:
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            is_mcp_tool = hasattr(type(tool), "__mro__") and any(
                c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
            )

            if is_mcp_tool:
                if tool.refresh_connection:  # type: ignore
                    try:
                        is_alive = await tool.is_alive()  # type: ignore
                        if not is_alive:
                            await tool.connect(force=True)  # type: ignore
                    except (RuntimeError, BaseException) as e:
                        log_warning(f"Failed to check if MCP tool is alive or to connect to it: {e}")
                        continue

                    try:
                        await tool.build_tools()  # type: ignore
                    except (RuntimeError, BaseException) as e:
                        log_warning(f"Failed to build tools for {str(tool)}: {e}")
                        continue

                # Only add the tool if it successfully connected and built its tools
                if check_mcp_tools and not tool.initialized:  # type: ignore
                    continue

            # Add the tool (MCP tools that passed checks, or any non-MCP tool)
            agent_tools.append(tool)

    # Add tools for accessing memory
    if agent.read_chat_history:
        agent_tools.append(_default_tools.get_chat_history_function(agent, session=session))
    if agent.read_tool_call_history:
        agent_tools.append(_default_tools.get_tool_call_history_function(agent, session=session))
    if agent.search_session_history:
        agent_tools.append(
            await _default_tools.aget_previous_sessions_messages_function(
                agent, num_history_sessions=agent.num_history_sessions, user_id=user_id
            )
        )

    if agent.enable_agentic_memory:
        agent_tools.append(_default_tools.get_update_user_memory_function(agent, user_id=user_id, async_mode=True))

    # Add learning machine tools (async)
    if agent._learning is not None:
        learning_tools = await agent._learning.aget_tools(
            user_id=user_id,
            session_id=session.session_id if session else None,
            agent_id=agent.id,
        )
        agent_tools.extend(learning_tools)

    if agent.enable_agentic_culture:
        agent_tools.append(_default_tools.get_update_cultural_knowledge_function(agent, async_mode=True))

    if agent.enable_agentic_state:
        agent_tools.append(
            Function(
                name="update_session_state",
                entrypoint=_default_tools.make_update_session_state_entrypoint(agent),
            )
        )

    # Add tools for accessing knowledge
    if resolved_knowledge is not None and agent.search_knowledge:
        # Use knowledge protocol's get_tools method
        aget_tools_fn = getattr(resolved_knowledge, "aget_tools", None)
        get_tools_fn = getattr(resolved_knowledge, "get_tools", None)

        if callable(aget_tools_fn):
            knowledge_tools = await aget_tools_fn(
                run_response=run_response,
                run_context=run_context,
                knowledge_filters=run_context.knowledge_filters,
                async_mode=True,
                enable_agentic_filters=agent.enable_agentic_knowledge_filters,
                agent=agent,
            )
            agent_tools.extend(knowledge_tools)
        elif callable(get_tools_fn):
            knowledge_tools = get_tools_fn(
                run_response=run_response,
                run_context=run_context,
                knowledge_filters=run_context.knowledge_filters,
                async_mode=True,
                enable_agentic_filters=agent.enable_agentic_knowledge_filters,
                agent=agent,
            )
            agent_tools.extend(knowledge_tools)
    elif agent.knowledge_retriever is not None and agent.search_knowledge:
        # Create search tool using custom knowledge_retriever
        agent_tools.append(
            _default_tools.create_knowledge_retriever_search_tool(
                agent,
                run_response=run_response,
                run_context=run_context,
                async_mode=True,
            )
        )

    if resolved_knowledge is not None and agent.update_knowledge:
        agent_tools.append(agent.add_to_knowledge)

    # Add tools for accessing skills
    if agent.skills is not None:
        agent_tools.extend(agent.skills.get_tools())

    return agent_tools


def parse_tools(
    agent: Agent,
    tools: List[Union[Toolkit, Callable, Function, Dict]],
    model: Model,
    run_context: Optional[RunContext] = None,
    async_mode: bool = False,
) -> List[Union[Function, dict]]:
    _function_names: List[str] = []
    _functions: List[Union[Function, dict]] = []
    agent._tool_instructions = []

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # Check if we need strict mode for the functions for the model
    strict = False
    if (
        output_schema is not None
        and (agent.structured_outputs or (not agent.use_json_mode))
        and model.supports_native_structured_outputs
    ):
        strict = True

    for tool in tools:
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
                _func._agent = agent
                # Respect the function's explicit strict setting if set
                effective_strict = strict if _func.strict is None else _func.strict
                _func.process_entrypoint(strict=effective_strict)
                if strict and _func.strict is None:
                    _func.strict = True
                if agent.tool_hooks is not None:
                    _func.tool_hooks = agent.tool_hooks
                _functions.append(_func)
                log_debug(f"Added tool {name} from {tool.name}")

            # Add instructions from the toolkit
            if tool.add_instructions and tool.instructions is not None:
                agent._tool_instructions.append(tool.instructions)

        elif isinstance(tool, Function):
            if tool.name in _function_names:
                continue
            _function_names.append(tool.name)

            tool = tool.model_copy(deep=True)
            # Respect the function's explicit strict setting if set
            effective_strict = strict if tool.strict is None else tool.strict
            tool.process_entrypoint(strict=effective_strict)

            tool._agent = agent
            if strict and tool.strict is None:
                tool.strict = True
            if agent.tool_hooks is not None:
                tool.tool_hooks = agent.tool_hooks
            _functions.append(tool)
            log_debug(f"Added tool {tool.name}")

            # Add instructions from the Function
            if tool.add_instructions and tool.instructions is not None:
                agent._tool_instructions.append(tool.instructions)

        elif callable(tool):
            try:
                function_name = tool.__name__

                if function_name in _function_names:
                    continue
                _function_names.append(function_name)

                _func = Function.from_callable(tool, strict=strict)
                # Detect @approval sentinel on raw callable
                _approval_type = getattr(tool, "_agno_approval_type", None)
                if _approval_type is not None:
                    _func.approval_type = _approval_type
                    if _approval_type == "required" and not any(
                        [_func.requires_user_input, _func.requires_confirmation, _func.external_execution]
                    ):
                        _func.requires_confirmation = True
                    elif _approval_type == "audit" and not any(
                        [_func.requires_user_input, _func.requires_confirmation, _func.external_execution]
                    ):
                        raise ValueError(
                            "@approval(type='audit') requires at least one HITL flag "
                            "('requires_confirmation', 'requires_user_input', or 'external_execution') "
                            "to be set on @tool()."
                        )
                _func = _func.model_copy(deep=True)
                _func._agent = agent
                if strict:
                    _func.strict = True
                if agent.tool_hooks is not None:
                    _func.tool_hooks = agent.tool_hooks
                _functions.append(_func)
                log_debug(f"Added tool {_func.name}")
            except Exception as e:
                log_warning(f"Could not add tool {tool}: {e}")

    return _functions


def determine_tools_for_model(
    agent: Agent,
    model: Model,
    processed_tools: List[Union[Toolkit, Callable, Function, Dict]],
    run_response: RunOutput,
    run_context: RunContext,
    session: AgentSession,
    async_mode: bool = False,
) -> List[Union[Function, dict]]:
    _functions: List[Union[Function, dict]] = []

    # Get Agent tools
    if processed_tools is not None and len(processed_tools) > 0:
        log_debug("Processing tools for model")
        _functions = parse_tools(
            agent, tools=processed_tools, model=model, run_context=run_context, async_mode=async_mode
        )

    # Update the session state for the functions
    if _functions:
        from inspect import signature

        # Check if any functions need media before collecting
        needs_media = any(
            any(param in signature(func.entrypoint).parameters for param in ["images", "videos", "audios", "files"])
            for func in _functions
            if isinstance(func, Function) and func.entrypoint is not None
        )

        # Only collect media if functions actually need them
        joint_images = collect_joint_images(run_response.input, session) if needs_media else None
        joint_files = collect_joint_files(run_response.input) if needs_media else None
        joint_audios = collect_joint_audios(run_response.input, session) if needs_media else None
        joint_videos = collect_joint_videos(run_response.input, session) if needs_media else None

        for func in _functions:  # type: ignore
            if isinstance(func, Function):
                func._run_context = run_context
                func._images = joint_images
                func._files = joint_files
                func._audios = joint_audios
                func._videos = joint_videos

    return _functions


# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------


def handle_external_execution_update(agent: Agent, run_messages: RunMessages, tool: ToolExecution):
    agent.model = cast(Model, agent.model)

    if tool.result is not None:
        for msg in run_messages.messages:
            # Skip if the message is already in the run_messages
            if msg.tool_call_id == tool.tool_call_id:
                break
        else:
            run_messages.messages.append(
                Message(
                    role=agent.model.tool_message_role,
                    content=tool.result,
                    tool_call_id=tool.tool_call_id,
                    tool_name=tool.tool_name,
                    tool_args=tool.tool_args,
                    tool_call_error=tool.tool_call_error,
                    stop_after_tool_call=tool.stop_after_tool_call,
                )
            )
        tool.external_execution_required = False
    else:
        raise ValueError(f"Tool {tool.tool_name} requires external execution, cannot continue run")


def handle_user_input_update(agent: Agent, tool: ToolExecution):
    for field in tool.user_input_schema or []:
        if not tool.tool_args:
            tool.tool_args = {}
        tool.tool_args[field.name] = field.value


def handle_get_user_input_tool_update(agent: Agent, run_messages: RunMessages, tool: ToolExecution):
    import json

    agent.model = cast(Model, agent.model)
    # Skipping tool without user_input_schema so that tool_call_id is not repeated
    if not hasattr(tool, "user_input_schema") or not tool.user_input_schema:
        return
    user_input_result = [
        {"name": user_input_field.name, "value": user_input_field.value}
        for user_input_field in tool.user_input_schema or []
    ]
    # Add the tool call result to the run_messages
    run_messages.messages.append(
        Message(
            role=agent.model.tool_message_role,
            content=f"User inputs retrieved: {json.dumps(user_input_result)}",
            tool_call_id=tool.tool_call_id,
            tool_name=tool.tool_name,
            tool_args=tool.tool_args,
            metrics=Metrics(duration=0),
        )
    )


def handle_ask_user_tool_update(agent: Agent, run_messages: RunMessages, tool: ToolExecution):
    import json

    agent.model = cast(Model, agent.model)
    if not hasattr(tool, "user_feedback_schema") or not tool.user_feedback_schema:
        return
    feedback_result = [
        {"question": q.question, "selected": q.selected_options or []} for q in tool.user_feedback_schema
    ]
    run_messages.messages.append(
        Message(
            role=agent.model.tool_message_role,
            content=f"User feedback received: {json.dumps(feedback_result)}",
            tool_call_id=tool.tool_call_id,
            tool_name=tool.tool_name,
            tool_args=tool.tool_args,
            metrics=Metrics(duration=0),
        )
    )


def _maybe_create_audit_approval(
    agent: "Agent", tool_execution: ToolExecution, run_response: RunOutput, status: str
) -> None:
    """Create an audit approval record if the tool has approval_type='audit'."""
    if getattr(tool_execution, "approval_type", None) == "audit":
        from agno.run.approval import create_audit_approval

        create_audit_approval(
            db=agent.db,
            tool_execution=tool_execution,
            run_response=run_response,
            status=status,
            agent_id=agent.id,
            agent_name=agent.name,
        )


async def _amaybe_create_audit_approval(
    agent: "Agent", tool_execution: ToolExecution, run_response: RunOutput, status: str
) -> None:
    """Async: create an audit approval record if the tool has approval_type='audit'."""
    if getattr(tool_execution, "approval_type", None) == "audit":
        from agno.run.approval import acreate_audit_approval

        await acreate_audit_approval(
            db=agent.db,
            tool_execution=tool_execution,
            run_response=run_response,
            status=status,
            agent_id=agent.id,
            agent_name=agent.name,
        )


def run_tool(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    tool: ToolExecution,
    functions: Optional[Dict[str, Function]] = None,
    stream_events: bool = False,
) -> Iterator[RunOutputEvent]:
    from agno.run.agent import CustomEvent

    agent.model = cast(Model, agent.model)
    # Execute the tool
    function_call = agent.model.get_function_call_to_run_from_tool_execution(tool, functions)
    function_call_results: List[Message] = []

    for call_result in agent.model.run_function_call(
        function_call=function_call,
        function_call_results=function_call_results,
    ):
        if isinstance(call_result, ModelResponse):
            if call_result.event == ModelResponseEvent.tool_call_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_tool_call_started_event(from_run_response=run_response, tool=tool),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

            if call_result.event == ModelResponseEvent.tool_call_completed.value and call_result.tool_executions:
                tool_execution = call_result.tool_executions[0]
                tool.result = tool_execution.result
                tool.tool_call_error = tool_execution.tool_call_error
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_tool_call_completed_event(
                            from_run_response=run_response, tool=tool, content=call_result.content
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                    if tool.tool_call_error:
                        yield handle_event(  # type: ignore
                            create_tool_call_error_event(
                                from_run_response=run_response, tool=tool, error=str(tool.result)
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
        # Yield CustomEvent instances from sync tool generators
        elif isinstance(call_result, CustomEvent):
            if stream_events:
                yield call_result  # type: ignore

    if len(function_call_results) > 0:
        run_messages.messages.extend(function_call_results)


def reject_tool_call(
    agent: Agent, run_messages: RunMessages, tool: ToolExecution, functions: Optional[Dict[str, Function]] = None
):
    agent.model = cast(Model, agent.model)
    function_call = agent.model.get_function_call_to_run_from_tool_execution(tool, functions)
    function_call.error = tool.confirmation_note or "Function call was rejected by the user"
    function_call_result = agent.model.create_function_call_result(
        function_call=function_call,
        success=False,
    )
    run_messages.messages.append(function_call_result)


async def arun_tool(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    tool: ToolExecution,
    functions: Optional[Dict[str, Function]] = None,
    stream_events: bool = False,
) -> AsyncIterator[RunOutputEvent]:
    from agno.run.agent import CustomEvent

    agent.model = cast(Model, agent.model)

    # Execute the tool
    function_call = agent.model.get_function_call_to_run_from_tool_execution(tool, functions)
    function_call_results: List[Message] = []

    async for call_result in agent.model.arun_function_calls(
        function_calls=[function_call],
        function_call_results=function_call_results,
        skip_pause_check=True,
    ):
        if isinstance(call_result, ModelResponse):
            if call_result.event == ModelResponseEvent.tool_call_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_tool_call_started_event(from_run_response=run_response, tool=tool),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
            if call_result.event == ModelResponseEvent.tool_call_completed.value and call_result.tool_executions:
                tool_execution = call_result.tool_executions[0]
                tool.result = tool_execution.result
                tool.tool_call_error = tool_execution.tool_call_error
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_tool_call_completed_event(
                            from_run_response=run_response, tool=tool, content=call_result.content
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                    if tool.tool_call_error:
                        yield handle_event(  # type: ignore
                            create_tool_call_error_event(
                                from_run_response=run_response, tool=tool, error=str(tool.result)
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
        # Yield CustomEvent instances from async tool generators
        elif isinstance(call_result, CustomEvent):
            if stream_events:
                yield call_result  # type: ignore

    if len(function_call_results) > 0:
        run_messages.messages.extend(function_call_results)


def handle_tool_call_updates(
    agent: Agent, run_response: RunOutput, run_messages: RunMessages, tools: List[Union[Function, dict]]
):
    agent.model = cast(Model, agent.model)
    _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

    for _t in run_response.tools or []:
        # Case 1: Handle confirmed tools and execute them
        if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
            # Tool is confirmed and hasn't been run before
            if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                # Consume the generator without yielding
                deque(run_tool(agent, run_response, run_messages, _t, functions=_functions), maxlen=0)
            else:
                reject_tool_call(agent, run_messages, _t, functions=_functions)
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            _maybe_create_audit_approval(agent, _t, run_response, "approved" if _t.confirmed is True else "rejected")
            _t.requires_confirmation = False

        # Case 2: Handle external execution required tools
        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(agent, run_messages=run_messages, tool=_t)
            _maybe_create_audit_approval(agent, _t, run_response, "approved")

        # Case 3a: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(agent, run_messages=run_messages, tool=_t)
            _t.requires_user_input = False
            _t.answered = True

        # Case 3b: User feedback (ask_user) required
        elif _t.tool_name == "ask_user" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_ask_user_tool_update(agent, run_messages=run_messages, tool=_t)
            _t.requires_user_input = False
            _t.answered = True

        # Case 4: Handle user input required tools
        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(agent, tool=_t)
            _t.requires_user_input = False
            _t.answered = True
            # Consume the generator without yielding
            deque(run_tool(agent, run_response, run_messages, _t, functions=_functions), maxlen=0)
            _maybe_create_audit_approval(agent, _t, run_response, "approved")


def handle_tool_call_updates_stream(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    tools: List[Union[Function, dict]],
    stream_events: bool = False,
) -> Iterator[RunOutputEvent]:
    agent.model = cast(Model, agent.model)
    _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

    for _t in run_response.tools or []:
        # Case 1: Handle confirmed tools and execute them
        if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
            # Tool is confirmed and hasn't been run before
            if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                yield from run_tool(
                    agent, run_response, run_messages, _t, functions=_functions, stream_events=stream_events
                )
            else:
                reject_tool_call(agent, run_messages, _t, functions=_functions)
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            _maybe_create_audit_approval(agent, _t, run_response, "approved" if _t.confirmed is True else "rejected")
            _t.requires_confirmation = False

        # Case 2: Handle external execution required tools
        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(agent, run_messages=run_messages, tool=_t)
            _maybe_create_audit_approval(agent, _t, run_response, "approved")

        # Case 3a: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(agent, run_messages=run_messages, tool=_t)
            _t.requires_user_input = False
            _t.answered = True

        # Case 3b: User feedback (ask_user) required
        elif _t.tool_name == "ask_user" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_ask_user_tool_update(agent, run_messages=run_messages, tool=_t)
            _t.requires_user_input = False
            _t.answered = True

        # Case 4: Handle user input required tools
        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(agent, tool=_t)
            yield from run_tool(
                agent, run_response, run_messages, _t, functions=_functions, stream_events=stream_events
            )
            _t.requires_user_input = False
            _t.answered = True
            _maybe_create_audit_approval(agent, _t, run_response, "approved")


async def ahandle_tool_call_updates(
    agent: Agent, run_response: RunOutput, run_messages: RunMessages, tools: List[Union[Function, dict]]
):
    agent.model = cast(Model, agent.model)
    _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

    for _t in run_response.tools or []:
        # Case 1: Handle confirmed tools and execute them
        if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
            # Tool is confirmed and hasn't been run before
            if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                async for _ in arun_tool(agent, run_response, run_messages, _t, functions=_functions):
                    pass
            else:
                reject_tool_call(agent, run_messages, _t, functions=_functions)
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            await _amaybe_create_audit_approval(
                agent, _t, run_response, "approved" if _t.confirmed is True else "rejected"
            )
            _t.requires_confirmation = False

        # Case 2: Handle external execution required tools
        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(agent, run_messages=run_messages, tool=_t)
            await _amaybe_create_audit_approval(agent, _t, run_response, "approved")
        # Case 3a: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(agent, run_messages=run_messages, tool=_t)
            _t.requires_user_input = False
            _t.answered = True
        # Case 3b: User feedback (ask_user) required
        elif _t.tool_name == "ask_user" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_ask_user_tool_update(agent, run_messages=run_messages, tool=_t)
            _t.requires_user_input = False
            _t.answered = True
        # Case 4: Handle user input required tools
        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(agent, tool=_t)
            async for _ in arun_tool(agent, run_response, run_messages, _t, functions=_functions):
                pass
            _t.requires_user_input = False
            _t.answered = True
            await _amaybe_create_audit_approval(agent, _t, run_response, "approved")


async def ahandle_tool_call_updates_stream(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    tools: List[Union[Function, dict]],
    stream_events: bool = False,
) -> AsyncIterator[RunOutputEvent]:
    agent.model = cast(Model, agent.model)
    _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

    for _t in run_response.tools or []:
        # Case 1: Handle confirmed tools and execute them
        if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
            # Tool is confirmed and hasn't been run before
            if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                async for event in arun_tool(
                    agent, run_response, run_messages, _t, functions=_functions, stream_events=stream_events
                ):
                    yield event
            else:
                reject_tool_call(agent, run_messages, _t, functions=_functions)
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            await _amaybe_create_audit_approval(
                agent, _t, run_response, "approved" if _t.confirmed is True else "rejected"
            )
            _t.requires_confirmation = False

        # Case 2: Handle external execution required tools
        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(agent, run_messages=run_messages, tool=_t)
            await _amaybe_create_audit_approval(agent, _t, run_response, "approved")
        # Case 3a: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(agent, run_messages=run_messages, tool=_t)
            _t.requires_user_input = False
            _t.answered = True
        # Case 3b: User feedback (ask_user) required
        elif _t.tool_name == "ask_user" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_ask_user_tool_update(agent, run_messages=run_messages, tool=_t)
            _t.requires_user_input = False
            _t.answered = True
        # Case 4: Handle user input required tools
        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(agent, tool=_t)
            async for event in arun_tool(
                agent, run_response, run_messages, _t, functions=_functions, stream_events=stream_events
            ):
                yield event
            _t.requires_user_input = False
            _t.answered = True
            await _amaybe_create_audit_approval(agent, _t, run_response, "approved")
