from collections import OrderedDict
from typing import Any, Callable, Dict, Optional

from agno.tools.function import Function
from agno.utils.log import log_debug, logger


class Toolkit:
    def __init__(
        self,
        name: str = "toolkit",
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        cache_results: bool = False,
        cache_ttl: int = 3600,
        cache_dir: Optional[str] = None,
    ):
        """Initialize a new Toolkit.

        Args:
            name: A descriptive name for the toolkit
            instructions: Instructions for the toolkit
            add_instructions: Whether to add instructions to the toolkit
            cache_results (bool): Enable in-memory caching of function results.
            cache_ttl (int): Time-to-live for cached results in seconds.
            cache_dir (Optional[str]): Directory to store cache files. Defaults to system temp dir.
        """
        self.name: str = name
        self.functions: Dict[str, Function] = OrderedDict()
        self.instructions: Optional[str] = instructions
        self.add_instructions: bool = add_instructions
        self.cache_results: bool = cache_results
        self.cache_ttl: int = cache_ttl
        self.cache_dir: Optional[str] = cache_dir

    def register(self, function: Callable[..., Any], sanitize_arguments: bool = True):
        """Register a function with the toolkit.

        Args:
            function: The callable to register

        Returns:
            The registered function
        """
        try:
            f = Function(
                name=function.__name__,
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
