from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

from agno.tools.function import Function
from agno.utils.log import log_debug, logger


class Toolkit:
    def __init__(
        self,
        name: str = "toolkit",
        tools: List[Callable] = [],
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        cache_results: bool = False,
        cache_ttl: int = 3600,
        cache_dir: Optional[str] = None,
        auto_register: bool = True,
    ):
        """Initialize a new Toolkit.

        Args:
            name: A descriptive name for the toolkit
            tools: List of tools to include in the toolkit
            instructions: Instructions for the toolkit
            add_instructions: Whether to add instructions to the toolkit
            include_tools: List of tool names to include in the toolkit
            exclude_tools: List of tool names to exclude from the toolkit
            cache_results (bool): Enable in-memory caching of function results.
            cache_ttl (int): Time-to-live for cached results in seconds.
            cache_dir (Optional[str]): Directory to store cache files. Defaults to system temp dir.
            auto_register (bool): Whether to automatically register all methods in the class.
        """
        self.name: str = name
        self.tools: List[Callable] = tools
        self.functions: Dict[str, Function] = OrderedDict()
        self.instructions: Optional[str] = instructions
        self.add_instructions: bool = add_instructions

        self.include_tools = include_tools
        self.exclude_tools = exclude_tools

        if include_tools or exclude_tools:
            available_tools = {tool.__name__ for tool in tools}

            if include_tools:
                missing_includes = set(include_tools) - available_tools
                if missing_includes:
                    raise ValueError(f"Included tool(s) not present in the toolkit: {', '.join(missing_includes)}")

            if exclude_tools:
                missing_excludes = set(exclude_tools) - available_tools
                if missing_excludes:
                    raise ValueError(f"Excluded tool(s) not present in the toolkit: {', '.join(missing_excludes)}")

        self.cache_results: bool = cache_results
        self.cache_ttl: int = cache_ttl
        self.cache_dir: Optional[str] = cache_dir

        # Automatically register all methods if auto_register is True
        if auto_register and self.tools:
            self._register_tools()

    def _register_tools(self) -> None:
        """Register all tools."""
        for tool in self.tools:
            self.register(tool)

    def register(self, function: Callable[..., Any], sanitize_arguments: bool = True, name: Optional[str] = None):
        """Register a function with the toolkit.

        Args:
            function: The callable to register
            sanitize_arguments: Whether to sanitize arguments before passing to the function
            name: Optional custom name for the function

        Returns:
            The registered function
        """
        try:
            tool_name = name or function.__name__
            if self.include_tools is not None and tool_name not in self.include_tools:
                return
            if self.exclude_tools is not None and tool_name in self.exclude_tools:
                return

            f = Function(
                name=tool_name,
                entrypoint=function,
                sanitize_arguments=sanitize_arguments,
                cache_results=self.cache_results,
                cache_dir=self.cache_dir,
                cache_ttl=self.cache_ttl,
            )
            self.functions[f.name] = f
            log_debug(f"Function: {f.name} registered with {self.name}")
        except Exception as e:
            logger.warning(f"Failed to create Function for: {function.__name__}")
            raise e

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name} functions={list(self.functions.keys())}>"

    def __str__(self):
        return self.__repr__()
