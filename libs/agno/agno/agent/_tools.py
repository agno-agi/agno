"""Tool resolution and formatting helpers for Agent."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Type,
    Union,
    cast,
)

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.models.base import Model
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.agent import (
    collect_joint_audios,
    collect_joint_files,
    collect_joint_images,
    collect_joint_videos,
)
from agno.utils.log import log_debug, log_warning


def raise_if_async_tools(agent: Agent) -> None:
    """Raise an exception if any tools contain async functions."""
    if agent.tools is None:
        return

    # Skip check if tools is a callable factory (not resolved yet)
    if callable(agent.tools) and not isinstance(agent.tools, (Toolkit, Function)):
        return

    _raise_if_async_tools_in_list(agent.tools)  # type: ignore[arg-type]


def _raise_if_async_tools_in_list(tools: List[Union[Toolkit, Callable, Function, Dict]]) -> None:
    """Raise an exception if any tools in the list contain async functions."""
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

    # Resolve callable factories for tools and knowledge
    resolve_callable_tools(agent, run_context)
    resolve_callable_knowledge(agent, run_context)

    # Connect tools that require connection management
    _init.connect_connectable_tools(agent)

    # Add provided tools (resolved from factory or static)
    resolved_tools = get_resolved_tools(agent, run_context)
    if resolved_tools:
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

    # Add tools for accessing knowledge (use resolved knowledge if available)
    resolved_knowledge = get_resolved_knowledge(agent, run_context)
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

    # Resolve callable factories for tools and knowledge
    await aresolve_callable_tools(agent, run_context)
    await aresolve_callable_knowledge(agent, run_context)

    # Connect tools that require connection management
    _init.connect_connectable_tools(agent)

    # Connect MCP tools
    await _init.connect_mcp_tools(agent)

    # Add provided tools (resolved from factory or static)
    resolved_tools = get_resolved_tools(agent, run_context)
    if resolved_tools:
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

    # Add tools for accessing knowledge (use resolved knowledge if available)
    resolved_knowledge = get_resolved_knowledge(agent, run_context)
    if resolved_knowledge is not None and agent.search_knowledge:
        # Use knowledge protocol's get_tools method
        aget_tools_fn = getattr(resolved_knowledge, "aget_tools", None)
        _get_tools_fn = getattr(resolved_knowledge, "get_tools", None)

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
        elif callable(_get_tools_fn):
            knowledge_tools = _get_tools_fn(
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


def model_should_return_structured_output(agent: Agent, run_context: Optional[RunContext] = None) -> bool:
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    agent.model = cast(Model, agent.model)
    return bool(
        agent.model.supports_native_structured_outputs
        and output_schema is not None
        and (not agent.use_json_mode or agent.structured_outputs)
    )


def get_response_format(
    agent: Agent, model: Optional[Model] = None, run_context: Optional[RunContext] = None
) -> Optional[Union[Dict, Type[BaseModel]]]:
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    model = cast(Model, model or agent.model)
    if output_schema is None:
        return None
    else:
        json_response_format: Dict[str, Any] = {"type": "json_object"}

        if model.supports_native_structured_outputs:
            if not agent.use_json_mode or agent.structured_outputs:
                log_debug("Setting Model.response_format to Agent.output_schema")
                return output_schema
            else:
                log_debug("Model supports native structured outputs but it is not enabled. Using JSON mode instead.")
                return json_response_format

        elif model.supports_json_schema_outputs:
            if agent.use_json_mode or (not agent.structured_outputs):
                log_debug("Setting Model.response_format to JSON response mode")
                # Handle JSON schema - pass through directly (user provides full provider format)
                if isinstance(output_schema, dict):
                    return output_schema
                # Handle Pydantic schema
                return {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_schema.__name__,
                        "schema": output_schema.model_json_schema(),
                    },
                }
            else:
                return None

        else:
            log_debug("Model does not support structured or JSON schema outputs.")
            return json_response_format


def resolve_run_dependencies(agent: Agent, run_context: RunContext) -> None:
    from inspect import iscoroutine, iscoroutinefunction, signature

    # Dependencies should already be resolved in run() method
    log_debug("Resolving dependencies")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Run dependencies are not a dict")
        return

    for key, value in run_context.dependencies.items():
        if iscoroutine(value) or iscoroutinefunction(value):
            log_warning(f"Dependency {key} is a coroutine. Use agent.arun() or agent.aprint_response() instead.")
            continue
        elif callable(value):
            try:
                sig = signature(value)

                # Build kwargs for the function
                kwargs: Dict[str, Any] = {}
                if "agent" in sig.parameters:
                    kwargs["agent"] = agent
                if "run_context" in sig.parameters:
                    kwargs["run_context"] = run_context

                # Run the function
                result = value(**kwargs)

                # Carry the result in the run context
                if result is not None:
                    run_context.dependencies[key] = result

            except Exception as e:
                log_warning(f"Failed to resolve dependencies for '{key}': {e}")
        else:
            run_context.dependencies[key] = value


async def aresolve_run_dependencies(agent: Agent, run_context: RunContext) -> None:
    from inspect import iscoroutine, iscoroutinefunction, signature

    log_debug("Resolving context (async)")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Run dependencies are not a dict")
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
                kwargs["agent"] = agent
            if "run_context" in sig.parameters:
                kwargs["run_context"] = run_context

            # Run the function
            result = value(**kwargs)
            if iscoroutine(result) or iscoroutinefunction(result):
                result = await result  # type: ignore

            run_context.dependencies[key] = result
        except Exception as e:
            log_warning(f"Failed to resolve context for '{key}': {e}")
