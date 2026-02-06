from __future__ import annotations

from inspect import isawaitable, iscoroutinefunction
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
from agno.knowledge.protocol import KnowledgeProtocol
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
    collect_joint_audios,
    collect_joint_files,
    collect_joint_images,
    collect_joint_videos,
)
from agno.utils.log import (
    log_debug,
    log_warning,
)


class AgentToolsTrait(AgentTraitBase):
    def _get_runtime_tools(
        self, run_context: Optional[RunContext] = None
    ) -> Optional[List[Union[Toolkit, Callable, Function, Dict]]]:
        if run_context is not None and run_context.tools is not None:
            return run_context.tools
        if self.tools is None or callable(self.tools):
            return None
        return list(self.tools)

    def _get_runtime_knowledge(self, run_context: Optional[RunContext] = None) -> Optional[KnowledgeProtocol]:
        if run_context is not None and run_context.knowledge is not None:
            return run_context.knowledge
        if self.knowledge is None:
            return None
        if callable(self.knowledge) and not isinstance(self.knowledge, KnowledgeProtocol):
            return None
        return cast(KnowledgeProtocol, self.knowledge)

    def _invoke_callable_resource_factory(self, factory: Callable[..., Any], run_context: RunContext) -> Any:
        from inspect import signature

        kwargs: Dict[str, Any] = {}
        try:
            sig = signature(factory)
            if "run_context" in sig.parameters:
                kwargs["run_context"] = run_context
            if "agent" in sig.parameters:
                kwargs["agent"] = self
            if "session_state" in sig.parameters:
                kwargs["session_state"] = run_context.session_state
        except Exception:
            kwargs = {}

        if kwargs:
            return factory(**kwargs)
        return factory()

    def _get_default_callable_cache_key(self, run_context: RunContext) -> Optional[str]:
        if run_context.user_id:
            return str(run_context.user_id)
        if run_context.session_id:
            return str(run_context.session_id)
        return None

    def _get_callable_cache_key(self, run_context: RunContext, kind: Literal["tools", "knowledge"]) -> Optional[str]:
        key_fn = self.callable_tools_cache_key if kind == "tools" else self.callable_knowledge_cache_key
        if key_fn is not None:
            if iscoroutinefunction(key_fn):
                raise RuntimeError(
                    f"Async callable {kind} cache key functions are not supported in sync runs. "
                    "Use async run APIs instead."
                )
            key_result = key_fn(run_context)
            if isawaitable(key_result):
                raise RuntimeError(
                    f"Async callable {kind} cache key functions are not supported in sync runs. "
                    "Use async run APIs instead."
                )
            if key_result is not None:
                return str(key_result)
        return self._get_default_callable_cache_key(run_context)

    async def _aget_callable_cache_key(
        self, run_context: RunContext, kind: Literal["tools", "knowledge"]
    ) -> Optional[str]:
        key_fn = self.callable_tools_cache_key if kind == "tools" else self.callable_knowledge_cache_key
        if key_fn is not None:
            key_result = key_fn(run_context)
            if isawaitable(key_result):
                key_result = await key_result
            if key_result is not None:
                return str(key_result)
        return self._get_default_callable_cache_key(run_context)

    def _resolve_runtime_tools_for_run(
        self, run_context: RunContext
    ) -> Optional[List[Union[Toolkit, Callable, Function, Dict]]]:
        # Use tools explicitly set on the run context when no agent-level tools are configured.
        if self.tools is None:
            return run_context.tools

        if not callable(self.tools):
            return list(self.tools)

        tools_factory = cast(Callable[..., List[Union[Toolkit, Callable, Function, Dict]]], self.tools)
        if iscoroutinefunction(tools_factory):
            raise RuntimeError(
                "Async tools factory is not supported in sync runs. "
                "Use `agent.arun()` / `agent.acontinue_run()` instead."
            )

        cache_key: Optional[str] = None
        if self.cache_callables:
            cache_key = self._get_callable_cache_key(run_context, kind="tools")
            if cache_key is not None and cache_key in self._callable_tools_cache:
                return self._callable_tools_cache[cache_key]

        tools_result = self._invoke_callable_resource_factory(tools_factory, run_context=run_context)
        if isawaitable(tools_result):
            raise RuntimeError(
                "Tools factory returned an awaitable in sync mode. "
                "Use `agent.arun()` / `agent.acontinue_run()` instead."
            )

        if tools_result is None:
            resolved_tools: List[Union[Toolkit, Callable, Function, Dict]] = []
        elif isinstance(tools_result, list):
            resolved_tools = tools_result
        elif isinstance(tools_result, tuple):
            resolved_tools = list(tools_result)
        else:
            raise TypeError(
                f"Callable tools factory must return a list (or tuple) of tools, got {type(tools_result).__name__}."
            )

        if self.cache_callables and cache_key is not None:
            self._callable_tools_cache[cache_key] = resolved_tools
        return resolved_tools

    async def _aresolve_runtime_tools_for_run(
        self, run_context: RunContext
    ) -> Optional[List[Union[Toolkit, Callable, Function, Dict]]]:
        # Use tools explicitly set on the run context when no agent-level tools are configured.
        if self.tools is None:
            return run_context.tools

        if not callable(self.tools):
            return list(self.tools)

        tools_factory = cast(Callable[..., List[Union[Toolkit, Callable, Function, Dict]]], self.tools)

        cache_key: Optional[str] = None
        if self.cache_callables:
            cache_key = await self._aget_callable_cache_key(run_context, kind="tools")
            if cache_key is not None and cache_key in self._callable_tools_cache:
                return self._callable_tools_cache[cache_key]

        tools_result = self._invoke_callable_resource_factory(tools_factory, run_context=run_context)
        if isawaitable(tools_result):
            tools_result = await tools_result

        if tools_result is None:
            resolved_tools: List[Union[Toolkit, Callable, Function, Dict]] = []
        elif isinstance(tools_result, list):
            resolved_tools = tools_result
        elif isinstance(tools_result, tuple):
            resolved_tools = list(tools_result)
        else:
            raise TypeError(
                f"Callable tools factory must return a list (or tuple) of tools, got {type(tools_result).__name__}."
            )

        if self.cache_callables and cache_key is not None:
            self._callable_tools_cache[cache_key] = resolved_tools
        return resolved_tools

    def _resolve_runtime_knowledge_for_run(self, run_context: RunContext) -> Optional[KnowledgeProtocol]:
        # Use knowledge explicitly set on the run context when no agent-level knowledge is configured.
        if self.knowledge is None:
            return run_context.knowledge

        if not callable(self.knowledge) or isinstance(self.knowledge, KnowledgeProtocol):
            return cast(KnowledgeProtocol, self.knowledge)

        knowledge_factory = cast(Callable[..., KnowledgeProtocol], self.knowledge)
        if iscoroutinefunction(knowledge_factory):
            raise RuntimeError(
                "Async knowledge factory is not supported in sync runs. "
                "Use `agent.arun()` / `agent.acontinue_run()` instead."
            )

        cache_key: Optional[str] = None
        if self.cache_callables:
            cache_key = self._get_callable_cache_key(run_context, kind="knowledge")
            if cache_key is not None and cache_key in self._callable_knowledge_cache:
                return self._callable_knowledge_cache[cache_key]

        knowledge_result = self._invoke_callable_resource_factory(knowledge_factory, run_context=run_context)
        if isawaitable(knowledge_result):
            raise RuntimeError(
                "Knowledge factory returned an awaitable in sync mode. "
                "Use `agent.arun()` / `agent.acontinue_run()` instead."
            )
        if knowledge_result is not None and not isinstance(knowledge_result, KnowledgeProtocol):
            raise TypeError(
                "Callable knowledge factory must return a KnowledgeProtocol instance or None, "
                f"got {type(knowledge_result).__name__}."
            )

        if self.cache_callables and cache_key is not None and knowledge_result is not None:
            self._callable_knowledge_cache[cache_key] = knowledge_result
        return cast(Optional[KnowledgeProtocol], knowledge_result)

    async def _aresolve_runtime_knowledge_for_run(self, run_context: RunContext) -> Optional[KnowledgeProtocol]:
        # Use knowledge explicitly set on the run context when no agent-level knowledge is configured.
        if self.knowledge is None:
            return run_context.knowledge

        if not callable(self.knowledge) or isinstance(self.knowledge, KnowledgeProtocol):
            return cast(KnowledgeProtocol, self.knowledge)

        knowledge_factory = cast(Callable[..., KnowledgeProtocol], self.knowledge)

        cache_key: Optional[str] = None
        if self.cache_callables:
            cache_key = await self._aget_callable_cache_key(run_context, kind="knowledge")
            if cache_key is not None and cache_key in self._callable_knowledge_cache:
                return self._callable_knowledge_cache[cache_key]

        knowledge_result = self._invoke_callable_resource_factory(knowledge_factory, run_context=run_context)
        if isawaitable(knowledge_result):
            knowledge_result = await knowledge_result
        if knowledge_result is not None and not isinstance(knowledge_result, KnowledgeProtocol):
            raise TypeError(
                "Callable knowledge factory must return a KnowledgeProtocol instance or None, "
                f"got {type(knowledge_result).__name__}."
            )

        if self.cache_callables and cache_key is not None and knowledge_result is not None:
            self._callable_knowledge_cache[cache_key] = knowledge_result
        return cast(Optional[KnowledgeProtocol], knowledge_result)

    def _resolve_runtime_resources(self, run_context: RunContext) -> None:
        run_context.tools = self._resolve_runtime_tools_for_run(run_context=run_context)
        run_context.knowledge = self._resolve_runtime_knowledge_for_run(run_context=run_context)

    async def _aresolve_runtime_resources(self, run_context: RunContext) -> None:
        run_context.tools = await self._aresolve_runtime_tools_for_run(run_context=run_context)
        run_context.knowledge = await self._aresolve_runtime_knowledge_for_run(run_context=run_context)

    @staticmethod
    def _dedupe_tools(tools: Sequence[Any]) -> List[Any]:
        deduped_tools: List[Any] = []
        seen_ids = set()
        for tool in tools:
            tool_id = id(tool)
            if tool_id in seen_ids:
                continue
            seen_ids.add(tool_id)
            deduped_tools.append(tool)
        return deduped_tools

    @staticmethod
    def _close_resource_sync(resource: Any) -> None:
        close_fn = getattr(resource, "close", None)
        if callable(close_fn):
            result = close_fn()
            if isawaitable(result):
                # Prevent RuntimeWarning by closing the unawaited coroutine
                if hasattr(result, "close"):
                    result.close()
                log_warning("close() returned an awaitable in sync cache clear; call aclear_callable_cache() instead.")

    @staticmethod
    async def _close_resource_async(resource: Any) -> None:
        aclose_fn = getattr(resource, "aclose", None)
        close_fn = getattr(resource, "close", None)

        if callable(aclose_fn):
            result = aclose_fn()
            if isawaitable(result):
                await result
            return

        if callable(close_fn):
            result = close_fn()
            if isawaitable(result):
                await result

    def clear_callable_cache(
        self,
        key: Optional[str] = None,
        user_id: Optional[str] = None,
        kind: Optional[Literal["tools", "knowledge"]] = None,
        close: bool = False,
    ) -> None:
        if kind not in (None, "tools", "knowledge"):
            raise ValueError("kind must be one of None, 'tools', or 'knowledge'")

        target_key = key if key is not None else user_id
        clear_tools = kind in (None, "tools")
        clear_knowledge = kind in (None, "knowledge")

        if clear_tools:
            selected_tools: List[Any] = []
            keys_to_clear = [target_key] if target_key is not None else list(self._callable_tools_cache.keys())
            for cache_key in keys_to_clear:
                cached_tools = self._callable_tools_cache.get(cache_key) if cache_key is not None else None
                if cached_tools is not None:
                    selected_tools.extend(cached_tools)
            if close and selected_tools:
                for tool in self._dedupe_tools(selected_tools):
                    try:
                        self._close_resource_sync(tool)
                    except Exception as e:
                        log_warning(f"Failed closing cached tool: {e}")
            if target_key is not None:
                self._callable_tools_cache.pop(target_key, None)
            else:
                self._callable_tools_cache.clear()

        if clear_knowledge:
            selected_knowledge: List[Any] = []
            keys_to_clear = [target_key] if target_key is not None else list(self._callable_knowledge_cache.keys())
            for cache_key in keys_to_clear:
                cached_knowledge = self._callable_knowledge_cache.get(cache_key) if cache_key is not None else None
                if cached_knowledge is not None:
                    selected_knowledge.append(cached_knowledge)
            if close and selected_knowledge:
                seen_ids = set()
                for knowledge in selected_knowledge:
                    knowledge_id = id(knowledge)
                    if knowledge_id in seen_ids:
                        continue
                    seen_ids.add(knowledge_id)
                    try:
                        self._close_resource_sync(knowledge)
                    except Exception as e:
                        log_warning(f"Failed closing cached knowledge: {e}")
            if target_key is not None:
                self._callable_knowledge_cache.pop(target_key, None)
            else:
                self._callable_knowledge_cache.clear()

    async def aclear_callable_cache(
        self,
        key: Optional[str] = None,
        user_id: Optional[str] = None,
        kind: Optional[Literal["tools", "knowledge"]] = None,
        close: bool = False,
    ) -> None:
        if kind not in (None, "tools", "knowledge"):
            raise ValueError("kind must be one of None, 'tools', or 'knowledge'")

        target_key = key if key is not None else user_id
        clear_tools = kind in (None, "tools")
        clear_knowledge = kind in (None, "knowledge")

        if clear_tools:
            selected_tools: List[Any] = []
            keys_to_clear = [target_key] if target_key is not None else list(self._callable_tools_cache.keys())
            for cache_key in keys_to_clear:
                cached_tools = self._callable_tools_cache.get(cache_key) if cache_key is not None else None
                if cached_tools is not None:
                    selected_tools.extend(cached_tools)
            if close and selected_tools:
                for tool in self._dedupe_tools(selected_tools):
                    try:
                        await self._close_resource_async(tool)
                    except Exception as e:
                        log_warning(f"Failed closing cached tool: {e}")
            if target_key is not None:
                self._callable_tools_cache.pop(target_key, None)
            else:
                self._callable_tools_cache.clear()

        if clear_knowledge:
            selected_knowledge: List[Any] = []
            keys_to_clear = [target_key] if target_key is not None else list(self._callable_knowledge_cache.keys())
            for cache_key in keys_to_clear:
                cached_knowledge = self._callable_knowledge_cache.get(cache_key) if cache_key is not None else None
                if cached_knowledge is not None:
                    selected_knowledge.append(cached_knowledge)
            if close and selected_knowledge:
                seen_ids = set()
                for knowledge in selected_knowledge:
                    knowledge_id = id(knowledge)
                    if knowledge_id in seen_ids:
                        continue
                    seen_ids.add(knowledge_id)
                    try:
                        await self._close_resource_async(knowledge)
                    except Exception as e:
                        log_warning(f"Failed closing cached knowledge: {e}")
            if target_key is not None:
                self._callable_knowledge_cache.pop(target_key, None)
            else:
                self._callable_knowledge_cache.clear()

    def get_tools(
        self,
        run_response: RunOutput,
        run_context: RunContext,
        session: AgentSession,
        user_id: Optional[str] = None,
    ) -> List[Union[Toolkit, Callable, Function, Dict]]:
        agent_tools: List[Union[Toolkit, Callable, Function, Dict]] = []
        runtime_tools = self._get_runtime_tools(run_context=run_context)
        runtime_knowledge = self._get_runtime_knowledge(run_context=run_context)

        # Connect tools that require connection management
        self._connect_connectable_tools(tools=runtime_tools)

        # Add provided tools
        if runtime_tools is not None:
            # If not running in async mode, raise if any tool is async
            self._raise_if_async_tools(tools=runtime_tools)
            agent_tools.extend(runtime_tools)

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
        if runtime_knowledge is not None and self.search_knowledge:
            # Use knowledge protocol's get_tools method
            get_tools_fn = getattr(runtime_knowledge, "get_tools", None)
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

        if runtime_knowledge is not None and self.update_knowledge:
            agent_tools.append(self.add_to_knowledge)

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
        runtime_tools = self._get_runtime_tools(run_context=run_context)
        runtime_knowledge = self._get_runtime_knowledge(run_context=run_context)

        # Connect tools that require connection management
        self._connect_connectable_tools(tools=runtime_tools)

        # Connect MCP tools
        await self._connect_mcp_tools(tools=runtime_tools)

        # Add provided tools
        if runtime_tools is not None:
            for tool in runtime_tools:
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
        if runtime_knowledge is not None and self.search_knowledge:
            # Use knowledge protocol's get_tools method
            aget_tools_fn = getattr(runtime_knowledge, "aget_tools", None)
            get_tools_fn = getattr(runtime_knowledge, "get_tools", None)

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

        if runtime_knowledge is not None and self.update_knowledge:
            agent_tools.append(self.add_to_knowledge)

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
