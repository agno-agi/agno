from __future__ import annotations

from inspect import iscoroutinefunction
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Type,
    Union,
    cast,
)

from pydantic import BaseModel

from agno.agent.trait.base import AgentTraitBase
from agno.models.base import Model
from agno.run import RunContext
from agno.run.agent import (
    RunOutput,
)
from agno.run.cancel import (
    acancel_run as acancel_run_global,
)
from agno.run.cancel import (
    cancel_run as cancel_run_global,
)
from agno.session import AgentSession
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.agent import (
    aresolve_knowledge,
    aresolve_tools,
    collect_joint_audios,
    collect_joint_files,
    collect_joint_images,
    collect_joint_videos,
    resolve_knowledge,
    resolve_tools,
)
from agno.utils.log import (
    log_debug,
    log_warning,
)


class AgentToolsTrait(AgentTraitBase):
    def _get_knowledge(self, run_context: Optional[RunContext] = None) -> Any:
        """Get the resolved knowledge instance.

        If knowledge was provided as a callable, it should be resolved during
        run/arun and stored in run_context.knowledge. This method returns the
        resolved instance from run_context if available, otherwise falls back to
        self.knowledge (for non-callable knowledge).
        """

        if run_context is not None and run_context.knowledge is not None:
            return run_context.knowledge
        if callable(self.knowledge):
            return None
        return self.knowledge

    def _is_tools_callable(self) -> bool:
        """Check if tools is a callable factory function (not a Toolkit/Function instance)."""

        return self.tools is not None and callable(self.tools) and not isinstance(self.tools, (Toolkit, Function))

    def _get_cache_key(self, run_context: RunContext, *, kind: Literal["tools", "knowledge"]) -> str:
        """Generate a cache key for callable tools/knowledge based on run context."""

        if kind == "tools" and self.callable_tools_cache_key is not None:
            return self.callable_tools_cache_key(run_context)
        if kind == "knowledge" and self.callable_knowledge_cache_key is not None:
            return self.callable_knowledge_cache_key(run_context)
        if run_context.user_id:
            return run_context.user_id
        return run_context.session_id

    def _try_close_cached_resource(self, resource: Any) -> None:
        """Best-effort close for cached resources (sync)."""

        from inspect import isawaitable

        close_fn = getattr(resource, "close", None)
        if callable(close_fn):
            try:
                result = close_fn()
                if isawaitable(result):
                    log_warning(
                        "close() returned an awaitable when clearing callable cache. "
                        "Use `await agent.aclear_callable_cache(close=True)` to close async resources."
                    )
            except Exception as e:
                log_warning(f"Failed to close cached resource {resource!r}: {e}")
            return

        aclose_fn = getattr(resource, "aclose", None)
        if callable(aclose_fn):
            log_warning(
                "Cached resource exposes `aclose()` but no `close()`. "
                "Use `await agent.aclear_callable_cache(close=True)` to close async resources."
            )

    async def _atry_close_cached_resource(self, resource: Any) -> None:
        """Best-effort close for cached resources (async)."""

        from inspect import isawaitable

        for attr in ("aclose", "close"):
            close_fn = getattr(resource, attr, None)
            if not callable(close_fn):
                continue
            try:
                result = close_fn()
                if isawaitable(result):
                    await result
            except Exception as e:
                log_warning(f"Failed to close cached resource {resource!r}: {e}")
            return

    def _try_close_cached_tools(self, tools: Sequence[Any]) -> None:
        """Best-effort close for cached tool instances (sync)."""

        seen: set[int] = set()
        for tool in tools:
            tool_id = id(tool)
            if tool_id in seen:
                continue
            seen.add(tool_id)
            self._try_close_cached_resource(tool)

    async def _atry_close_cached_tools(self, tools: Sequence[Any]) -> None:
        """Best-effort close for cached tool instances (async)."""

        seen: set[int] = set()
        for tool in tools:
            tool_id = id(tool)
            if tool_id in seen:
                continue
            seen.add(tool_id)
            await self._atry_close_cached_resource(tool)

    def clear_callable_cache(
        self,
        key: Optional[str] = None,
        user_id: Optional[str] = None,
        *,
        kind: Optional[Literal["tools", "knowledge"]] = None,
        close: bool = False,
    ) -> None:
        """Clear the callable tools and knowledge cache."""

        cache_key = key or user_id
        if cache_key is not None:
            if kind in (None, "tools"):
                tools = self._tool_cache.pop(cache_key, None)
                if close and tools:
                    self._try_close_cached_tools(tools)
            if kind in (None, "knowledge"):
                knowledge = self._knowledge_cache.pop(cache_key, None)
                if close and knowledge is not None:
                    self._try_close_cached_resource(knowledge)
        else:
            if kind in (None, "tools"):
                if close:
                    for tools in self._tool_cache.values():
                        self._try_close_cached_tools(tools)
                self._tool_cache.clear()
            if kind in (None, "knowledge"):
                if close:
                    for knowledge in self._knowledge_cache.values():
                        self._try_close_cached_resource(knowledge)
                self._knowledge_cache.clear()

    async def aclear_callable_cache(
        self,
        key: Optional[str] = None,
        user_id: Optional[str] = None,
        *,
        kind: Optional[Literal["tools", "knowledge"]] = None,
        close: bool = False,
    ) -> None:
        """Async version of clear_callable_cache."""

        cache_key = key or user_id
        if cache_key is not None:
            if kind in (None, "tools"):
                tools = self._tool_cache.pop(cache_key, None)
                if close and tools:
                    await self._atry_close_cached_tools(tools)
            if kind in (None, "knowledge"):
                knowledge = self._knowledge_cache.pop(cache_key, None)
                if close and knowledge is not None:
                    await self._atry_close_cached_resource(knowledge)
        else:
            if kind in (None, "tools"):
                if close:
                    for tools in self._tool_cache.values():
                        await self._atry_close_cached_tools(tools)
                self._tool_cache.clear()
            if kind in (None, "knowledge"):
                if close:
                    for knowledge in self._knowledge_cache.values():
                        await self._atry_close_cached_resource(knowledge)
                self._knowledge_cache.clear()

    def _resolve_callables(
        self,
        run_context: RunContext,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Resolve callable tools and knowledge, storing results in run_context."""

        if callable(self.knowledge):
            cache_key = self._get_cache_key(run_context, kind="knowledge")
            if self.cache_callables and cache_key in self._knowledge_cache:
                run_context.knowledge = self._knowledge_cache[cache_key]
            else:
                try:
                    run_context.knowledge = resolve_knowledge(
                        knowledge=self.knowledge,
                        agent=cast(Any, self),
                        session_state=session_state,
                        run_context=run_context,
                    )
                except Exception as e:
                    raise RuntimeError(
                        "Failed to resolve callable knowledge "
                        f"(cache_key={cache_key}, user_id={run_context.user_id}, session_id={run_context.session_id}): {e}"
                    ) from e
                if self.cache_callables:
                    self._knowledge_cache[cache_key] = run_context.knowledge
        else:
            run_context.knowledge = self.knowledge

        if self._is_tools_callable():
            cache_key = self._get_cache_key(run_context, kind="tools")
            if self.cache_callables and cache_key in self._tool_cache:
                run_context.tools = self._tool_cache[cache_key]
            else:
                try:
                    tools_callable = cast(Callable[..., Any], self.tools)
                    run_context.tools = resolve_tools(
                        tools=tools_callable,
                        agent=cast(Any, self),
                        session_state=session_state,
                        run_context=run_context,
                    )
                except Exception as e:
                    raise RuntimeError(
                        "Failed to resolve callable tools "
                        f"(cache_key={cache_key}, user_id={run_context.user_id}, session_id={run_context.session_id}): {e}"
                    ) from e
                if self.cache_callables:
                    self._tool_cache[cache_key] = run_context.tools
        else:
            run_context.tools = self.tools  # type: ignore

    async def _aresolve_callables(
        self,
        run_context: RunContext,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async version of _resolve_callables."""

        if callable(self.knowledge):
            cache_key = self._get_cache_key(run_context, kind="knowledge")
            if self.cache_callables and cache_key in self._knowledge_cache:
                run_context.knowledge = self._knowledge_cache[cache_key]
            else:
                try:
                    run_context.knowledge = await aresolve_knowledge(
                        knowledge=self.knowledge,
                        agent=cast(Any, self),
                        session_state=session_state,
                        run_context=run_context,
                    )
                except Exception as e:
                    raise RuntimeError(
                        "Failed to resolve callable knowledge "
                        f"(cache_key={cache_key}, user_id={run_context.user_id}, session_id={run_context.session_id}): {e}"
                    ) from e
                if self.cache_callables:
                    self._knowledge_cache[cache_key] = run_context.knowledge
        else:
            run_context.knowledge = self.knowledge

        if self._is_tools_callable():
            cache_key = self._get_cache_key(run_context, kind="tools")
            if self.cache_callables and cache_key in self._tool_cache:
                run_context.tools = self._tool_cache[cache_key]
            else:
                try:
                    tools_callable = cast(Callable[..., Any], self.tools)
                    run_context.tools = await aresolve_tools(
                        tools=tools_callable,
                        agent=cast(Any, self),
                        session_state=session_state,
                        run_context=run_context,
                    )
                except Exception as e:
                    raise RuntimeError(
                        "Failed to resolve callable tools "
                        f"(cache_key={cache_key}, user_id={run_context.user_id}, session_id={run_context.session_id}): {e}"
                    ) from e
                if self.cache_callables:
                    self._tool_cache[cache_key] = run_context.tools
        else:
            run_context.tools = self.tools  # type: ignore

    def _get_tools(
        self, run_context: Optional[RunContext] = None
    ) -> Optional[List[Union[Toolkit, Callable, Function, Dict]]]:
        """Get the resolved tools list."""

        if run_context is not None and run_context.tools is not None:
            return run_context.tools
        if self._is_tools_callable():
            return None
        return self.tools  # type: ignore

    def get_tools(
        self,
        run_response: RunOutput,
        run_context: RunContext,
        session: AgentSession,
        user_id: Optional[str] = None,
    ) -> List[Union[Toolkit, Callable, Function, Dict]]:
        agent_tools: List[Union[Toolkit, Callable, Function, Dict]] = []

        # Connect tools that require connection management
        self._connect_connectable_tools(run_context=run_context)

        tools = self._get_tools(run_context=run_context)
        knowledge = self._get_knowledge(run_context=run_context)

        # Add provided tools
        if tools is not None:
            # If not running in async mode, raise if any tool is async
            self._raise_if_async_tools(run_context=run_context)
            agent_tools.extend(tools)

        # Add tools for accessing memory
        if self.read_chat_history:
            agent_tools.append(self._get_chat_history_function(session=session))
        if self.read_tool_call_history:
            agent_tools.append(self._get_tool_call_history_function(session=session))
        if self.search_session_history:
            agent_tools.append(
                self._get_previous_sessions_messages_function(
                    num_history_sessions=self.num_history_sessions, user_id=user_id
                )
            )

        if self.enable_agentic_memory:
            agent_tools.append(self._get_update_user_memory_function(user_id=user_id, async_mode=False))

        # Add learning machine tools
        if self._learning is not None:
            learning_tools = self._learning.get_tools(
                user_id=user_id,
                session_id=session.session_id if session else None,
                agent_id=self.id,
            )
            agent_tools.extend(learning_tools)

        if self.enable_agentic_culture:
            agent_tools.append(self._get_update_cultural_knowledge_function(async_mode=False))

        if self.enable_agentic_state:
            agent_tools.append(Function(name="update_session_state", entrypoint=self._update_session_state_tool))

        # Add tools for accessing knowledge
        if knowledge is not None and self.search_knowledge:
            # Use knowledge protocol's get_tools method
            get_tools_fn = getattr(knowledge, "get_tools", None)
            if callable(get_tools_fn):
                knowledge_tools = get_tools_fn(
                    run_response=run_response,
                    run_context=run_context,
                    knowledge_filters=run_context.knowledge_filters,
                    async_mode=False,
                    enable_agentic_filters=self.enable_agentic_knowledge_filters,
                    agent=self,
                )
                agent_tools.extend(knowledge_tools)
        elif self.knowledge_retriever is not None and self.search_knowledge:
            # Create search tool using custom knowledge_retriever
            agent_tools.append(
                self._create_knowledge_retriever_search_tool(
                    run_response=run_response,
                    run_context=run_context,
                    async_mode=False,
                )
            )

        if knowledge is not None and self.update_knowledge:
            agent_tools.append(self._create_add_to_knowledge_tool(knowledge=knowledge))

        # Add tools for accessing skills
        if self.skills is not None:
            agent_tools.extend(self.skills.get_tools())

        return agent_tools

    async def aget_tools(
        self,
        run_response: RunOutput,
        run_context: RunContext,
        session: AgentSession,
        user_id: Optional[str] = None,
        check_mcp_tools: bool = True,
    ) -> List[Union[Toolkit, Callable, Function, Dict]]:
        agent_tools: List[Union[Toolkit, Callable, Function, Dict]] = []

        # Connect tools that require connection management
        self._connect_connectable_tools(run_context=run_context)

        # Connect MCP tools
        await self._connect_mcp_tools(run_context=run_context)

        tools = self._get_tools(run_context=run_context)
        knowledge = self._get_knowledge(run_context=run_context)

        # Add provided tools
        if tools is not None:
            for tool in tools:
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
        if self.read_chat_history:
            agent_tools.append(self._get_chat_history_function(session=session))
        if self.read_tool_call_history:
            agent_tools.append(self._get_tool_call_history_function(session=session))
        if self.search_session_history:
            agent_tools.append(
                await self._aget_previous_sessions_messages_function(
                    num_history_sessions=self.num_history_sessions, user_id=user_id
                )
            )

        if self.enable_agentic_memory:
            agent_tools.append(self._get_update_user_memory_function(user_id=user_id, async_mode=True))

        # Add learning machine tools (async)
        if self._learning is not None:
            learning_tools = await self._learning.aget_tools(
                user_id=user_id,
                session_id=session.session_id if session else None,
                agent_id=self.id,
            )
            agent_tools.extend(learning_tools)

        if self.enable_agentic_culture:
            agent_tools.append(self._get_update_cultural_knowledge_function(async_mode=True))

        if self.enable_agentic_state:
            agent_tools.append(Function(name="update_session_state", entrypoint=self._update_session_state_tool))

        # Add tools for accessing knowledge
        if knowledge is not None and self.search_knowledge:
            # Use knowledge protocol's get_tools method
            aget_tools_fn = getattr(knowledge, "aget_tools", None)
            get_tools_fn = getattr(knowledge, "get_tools", None)

            if callable(aget_tools_fn):
                knowledge_tools = await aget_tools_fn(
                    run_response=run_response,
                    run_context=run_context,
                    knowledge_filters=run_context.knowledge_filters,
                    async_mode=True,
                    enable_agentic_filters=self.enable_agentic_knowledge_filters,
                    agent=self,
                )
                agent_tools.extend(knowledge_tools)
            elif callable(get_tools_fn):
                knowledge_tools = get_tools_fn(
                    run_response=run_response,
                    run_context=run_context,
                    knowledge_filters=run_context.knowledge_filters,
                    async_mode=True,
                    enable_agentic_filters=self.enable_agentic_knowledge_filters,
                    agent=self,
                )
                agent_tools.extend(knowledge_tools)
        elif self.knowledge_retriever is not None and self.search_knowledge:
            # Create search tool using custom knowledge_retriever
            agent_tools.append(
                self._create_knowledge_retriever_search_tool(
                    run_response=run_response,
                    run_context=run_context,
                    async_mode=True,
                )
            )

        if knowledge is not None and self.update_knowledge:
            agent_tools.append(self._create_add_to_knowledge_tool(knowledge=knowledge))

        # Add tools for accessing skills
        if self.skills is not None:
            agent_tools.extend(self.skills.get_tools())

        return agent_tools

    def _parse_tools(
        self,
        tools: List[Union[Toolkit, Callable, Function, Dict]],
        model: Model,
        run_context: Optional[RunContext] = None,
        async_mode: bool = False,
    ) -> List[Union[Function, dict]]:
        _function_names = []
        _functions: List[Union[Function, dict]] = []
        self._tool_instructions = []

        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        # Check if we need strict mode for the functions for the model
        strict = False
        if (
            output_schema is not None
            and (self.structured_outputs or (not self.use_json_mode))
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
                    _func._agent = self
                    # Respect the function's explicit strict setting if set
                    effective_strict = strict if _func.strict is None else _func.strict
                    _func.process_entrypoint(strict=effective_strict)
                    if strict and _func.strict is None:
                        _func.strict = True
                    if self.tool_hooks is not None:
                        _func.tool_hooks = self.tool_hooks
                    _functions.append(_func)
                    log_debug(f"Added tool {name} from {tool.name}")

                # Add instructions from the toolkit
                if tool.add_instructions and tool.instructions is not None:
                    self._tool_instructions.append(tool.instructions)

            elif isinstance(tool, Function):
                if tool.name in _function_names:
                    continue
                _function_names.append(tool.name)

                # Respect the function's explicit strict setting if set
                effective_strict = strict if tool.strict is None else tool.strict
                tool.process_entrypoint(strict=effective_strict)
                tool = tool.model_copy(deep=True)

                tool._agent = self
                if strict and tool.strict is None:
                    tool.strict = True
                if self.tool_hooks is not None:
                    tool.tool_hooks = self.tool_hooks
                _functions.append(tool)
                log_debug(f"Added tool {tool.name}")

                # Add instructions from the Function
                if tool.add_instructions and tool.instructions is not None:
                    self._tool_instructions.append(tool.instructions)

            elif callable(tool):
                try:
                    function_name = tool.__name__

                    if function_name in _function_names:
                        continue
                    _function_names.append(function_name)

                    _func = Function.from_callable(tool, strict=strict)
                    _func = _func.model_copy(deep=True)
                    _func._agent = self
                    if strict:
                        _func.strict = True
                    if self.tool_hooks is not None:
                        _func.tool_hooks = self.tool_hooks
                    _functions.append(_func)
                    log_debug(f"Added tool {_func.name}")
                except Exception as e:
                    log_warning(f"Could not add tool {tool}: {e}")

        return _functions

    def _determine_tools_for_model(
        self,
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
            _functions = self._parse_tools(
                tools=processed_tools, model=model, run_context=run_context, async_mode=async_mode
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

    def _model_should_return_structured_output(self, run_context: Optional[RunContext] = None):
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        self.model = cast(Model, self.model)
        return bool(
            self.model.supports_native_structured_outputs
            and output_schema is not None
            and (not self.use_json_mode or self.structured_outputs)
        )

    def _get_response_format(
        self, model: Optional[Model] = None, run_context: Optional[RunContext] = None
    ) -> Optional[Union[Dict, Type[BaseModel]]]:
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        model = cast(Model, model or self.model)
        if output_schema is None:
            return None
        else:
            json_response_format = {"type": "json_object"}

            if model.supports_native_structured_outputs:
                if not self.use_json_mode or self.structured_outputs:
                    log_debug("Setting Model.response_format to Agent.output_schema")
                    return output_schema
                else:
                    log_debug(
                        "Model supports native structured outputs but it is not enabled. Using JSON mode instead."
                    )
                    return json_response_format

            elif model.supports_json_schema_outputs:
                if self.use_json_mode or (not self.structured_outputs):
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

    def _resolve_run_dependencies(self, run_context: RunContext) -> None:
        from inspect import iscoroutine, signature

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
                        kwargs["agent"] = self
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

    async def _aresolve_run_dependencies(self, run_context: RunContext) -> None:
        from inspect import iscoroutine, signature

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
                    kwargs["agent"] = self
                if "run_context" in sig.parameters:
                    kwargs["run_context"] = run_context

                # Run the function
                result = value(**kwargs)
                if iscoroutine(result) or iscoroutinefunction(result):
                    result = await result  # type: ignore

                run_context.dependencies[key] = result
            except Exception as e:
                log_warning(f"Failed to resolve context for '{key}': {e}")

    def _get_agent_data(self) -> Dict[str, Any]:
        agent_data: Dict[str, Any] = {}
        if self.name is not None:
            agent_data["name"] = self.name
        if self.id is not None:
            agent_data["agent_id"] = self.id
        if self.model is not None:
            agent_data["model"] = self.model.to_dict()
        return agent_data

    @staticmethod
    def cancel_run(run_id: str) -> bool:
        """Cancel a running agent execution.

        Args:
            run_id (str): The run_id to cancel.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        return cancel_run_global(run_id)

    @staticmethod
    async def acancel_run(run_id: str) -> bool:
        """Cancel a running agent execution (async version).

        Args:
            run_id (str): The run_id to cancel.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        return await acancel_run_global(run_id)
