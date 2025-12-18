from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning, logger


class Toolkit:
    # Set to True for toolkits that require connection management (e.g., database connections)
    # When True, the Agent will automatically call connect() before using tools and close() after
    _requires_connect: bool = False

    def __init__(
        self,
        name: str = "toolkit",
        tools: Sequence[Union[Callable[..., Any], Function]] = [],
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        requires_confirmation_tools: Optional[list[str]] = None,
        external_execution_required_tools: Optional[list[str]] = None,
        stop_after_tool_call_tools: Optional[List[str]] = None,
        show_result_tools: Optional[List[str]] = None,
        cache_results: bool = False,
        cache_ttl: int = 3600,
        cache_dir: Optional[str] = None,
        auto_register: bool = True,
    ):
        """Initialize a new Toolkit.

        Args:
            name: A descriptive name for the toolkit
            tools: List of tools to include in the toolkit (can be callables or Function objects from @tool decorator)
            instructions: Instructions for the toolkit
            add_instructions: Whether to add instructions to the toolkit
            include_tools: List of tool names to include in the toolkit
            exclude_tools: List of tool names to exclude from the toolkit
            requires_confirmation_tools: List of tool names that require user confirmation
            external_execution_required_tools: List of tool names that will be executed outside of the agent loop
            cache_results (bool): Enable in-memory caching of function results.
            cache_ttl (int): Time-to-live for cached results in seconds.
            cache_dir (Optional[str]): Directory to store cache files. Defaults to system temp dir.
            auto_register (bool): Whether to automatically register all methods in the class.
            stop_after_tool_call_tools (Optional[List[str]]): List of function names that should stop the agent after execution.
            show_result_tools (Optional[List[str]]): List of function names whose results should be shown.
        """
        self.name: str = name
        self.tools: Sequence[Union[Callable[..., Any], Function]] = tools
        self.functions: Dict[str, Function] = OrderedDict()
        self.instructions: Optional[str] = instructions
        self.add_instructions: bool = add_instructions

        self.requires_confirmation_tools: list[str] = requires_confirmation_tools or []
        self.external_execution_required_tools: list[str] = external_execution_required_tools or []

        self.stop_after_tool_call_tools: list[str] = stop_after_tool_call_tools or []
        self.show_result_tools: list[str] = show_result_tools or []

        self._check_tools_filters(
            available_tools=[self._get_tool_name(tool) for tool in tools],
            include_tools=include_tools,
            exclude_tools=exclude_tools,
        )

        self.include_tools = include_tools
        self.exclude_tools = exclude_tools

        self.cache_results: bool = cache_results
        self.cache_ttl: int = cache_ttl
        self.cache_dir: Optional[str] = cache_dir

        # Automatically register all methods if auto_register is True
        if auto_register and self.tools:
            self._register_tools()

    def _get_tool_name(self, tool: Union[Callable[..., Any], Function]) -> str:
        """Get the name of a tool, whether it's a Function or callable."""
        if isinstance(tool, Function):
            return tool.name
        return tool.__name__

    def _check_tools_filters(
        self,
        available_tools: List[str],
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
    ) -> None:
        """Check if `include_tools` and `exclude_tools` are valid"""
        if include_tools or exclude_tools:
            if include_tools:
                missing_includes = set(include_tools) - set(available_tools)
                if missing_includes:
                    raise ValueError(f"Included tool(s) not present in the toolkit: {', '.join(missing_includes)}")

            if exclude_tools:
                missing_excludes = set(exclude_tools) - set(available_tools)
                if missing_excludes:
                    raise ValueError(f"Excluded tool(s) not present in the toolkit: {', '.join(missing_excludes)}")

        if self.requires_confirmation_tools:
            missing_requires_confirmation = set(self.requires_confirmation_tools) - set(available_tools)
            if missing_requires_confirmation:
                log_warning(
                    f"Requires confirmation tool(s) not present in the toolkit: {', '.join(missing_requires_confirmation)}"
                )

        if self.external_execution_required_tools:
            missing_external_execution_required = set(self.external_execution_required_tools) - set(available_tools)
            if missing_external_execution_required:
                log_warning(
                    f"External execution required tool(s) not present in the toolkit: {', '.join(missing_external_execution_required)}"
                )

        if self.stop_after_tool_call_tools:
            missing_stop_after_tool_call = set(self.stop_after_tool_call_tools) - set(available_tools)
            if missing_stop_after_tool_call:
                log_warning(
                    f"Stop after tool call tool(s) not present in the toolkit: {', '.join(missing_stop_after_tool_call)}"
                )

        if self.show_result_tools:
            missing_show_result = set(self.show_result_tools) - set(available_tools)
            if missing_show_result:
                log_warning(f"Show result tool(s) not present in the toolkit: {', '.join(missing_show_result)}")

    def _register_tools(self) -> None:
        """Register all tools."""
        for tool in self.tools:
            self.register(tool)

    def register(self, function: Union[Callable[..., Any], Function], name: Optional[str] = None) -> None:
        """Register a function with the toolkit.

        This method supports both regular callables and Function objects (from @tool decorator).
        When a Function object is passed (e.g., from a @tool decorated method), it will:
        1. Extract the configuration from the Function object
        2. Look for a bound method with the same name on `self`
        3. Create a new Function with the bound method as entrypoint, preserving decorator settings

        Args:
            function: The callable or Function object to register
            name: Optional custom name for the function

        Returns:
            The registered function
        """
        try:
            # Handle Function objects (from @tool decorator)
            if isinstance(function, Function):
                return self._register_decorated_tool(function, name)

            # Handle regular callables
            tool_name = name or function.__name__
            if self.include_tools is not None and tool_name not in self.include_tools:
                return
            if self.exclude_tools is not None and tool_name in self.exclude_tools:
                return

            f = Function(
                name=tool_name,
                entrypoint=function,
                cache_results=self.cache_results,
                cache_dir=self.cache_dir,
                cache_ttl=self.cache_ttl,
                requires_confirmation=tool_name in self.requires_confirmation_tools,
                external_execution=tool_name in self.external_execution_required_tools,
                stop_after_tool_call=tool_name in self.stop_after_tool_call_tools,
                show_result=tool_name in self.show_result_tools or tool_name in self.stop_after_tool_call_tools,
            )
            self.functions[f.name] = f
            log_debug(f"Function: {f.name} registered with {self.name}")
        except Exception as e:
            func_name = self._get_tool_name(function)
            logger.warning(f"Failed to create Function for: {func_name}")
            raise e

    def _register_decorated_tool(self, function: Function, name: Optional[str] = None) -> None:
        """Register a Function object from @tool decorator, binding it to self.

        When @tool decorator is used on a class method, it creates a Function with an unbound
        method as entrypoint. This method creates a bound version of the entrypoint that
        includes `self`, preserving all decorator settings.

        Args:
            function: The Function object from @tool decorator
            name: Optional custom name override
        """
        import inspect

        tool_name = name or function.name
        if self.include_tools is not None and len(self.include_tools) > 0 and tool_name not in self.include_tools:
            return
        if self.exclude_tools is not None and len(self.exclude_tools) > 0 and tool_name in self.exclude_tools:
            return

        # Get the original entrypoint from the Function
        if function.entrypoint is None:
            log_warning(f"Function '{tool_name}' has no entrypoint, skipping registration")
            return

        original_func = function.entrypoint

        # Check if the function expects 'self' as first argument (i.e., it's an unbound method)
        sig = inspect.signature(original_func)
        params = list(sig.parameters.keys())

        if params and params[0] == "self":
            # Create a bound method by wrapping the function to include self
            def make_bound_method(func, instance):
                def bound(*args, **kwargs):
                    return func(instance, *args, **kwargs)

                # Preserve function metadata for debugging
                bound.__name__ = getattr(func, "__name__", tool_name)
                bound.__doc__ = getattr(func, "__doc__", None)
                return bound

            bound_method = make_bound_method(original_func, self)
        else:
            # Function doesn't expect self (e.g., static method or already bound)
            bound_method = original_func

        # decorator settings take precedence, then toolkit settings
        stop_after = function.stop_after_tool_call or tool_name in self.stop_after_tool_call_tools
        show_result = function.show_result or tool_name in self.show_result_tools or stop_after
        requires_confirmation = function.requires_confirmation or tool_name in self.requires_confirmation_tools
        external_execution = function.external_execution or tool_name in self.external_execution_required_tools

        # Create new Function with bound method, preserving decorator settings
        f = Function(
            name=tool_name,
            description=function.description,
            parameters=function.parameters,
            strict=function.strict,
            instructions=function.instructions,
            add_instructions=function.add_instructions,
            entrypoint=bound_method,
            skip_entrypoint_processing=True,  # Parameters already processed by decorator
            show_result=show_result,
            stop_after_tool_call=stop_after,
            pre_hook=function.pre_hook,
            post_hook=function.post_hook,
            tool_hooks=function.tool_hooks,
            requires_confirmation=requires_confirmation,
            requires_user_input=function.requires_user_input,
            user_input_fields=function.user_input_fields,
            user_input_schema=function.user_input_schema,
            external_execution=external_execution,
            cache_results=function.cache_results if function.cache_results else self.cache_results,
            cache_dir=function.cache_dir if function.cache_dir else self.cache_dir,
            cache_ttl=function.cache_ttl if function.cache_ttl != 3600 else self.cache_ttl,
        )
        self.functions[f.name] = f
        log_debug(f"Function: {f.name} registered with {self.name} (from @tool decorator)")

    @property
    def requires_connect(self) -> bool:
        """Whether the toolkit requires connection management."""
        return self._requires_connect

    def connect(self) -> None:
        """
        Establish any required connections for the toolkit.
        Override this method in subclasses that require connection management.
        Called automatically by the Agent when _requires_connect is True.
        """
        pass

    def close(self) -> None:
        """
        Close any open connections for the toolkit.
        Override this method in subclasses that require connection management.
        Called automatically by the Agent when _requires_connect is True.
        """
        pass

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name} functions={list(self.functions.keys())}>"

    def __str__(self):
        return self.__repr__()
