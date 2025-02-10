from collections import OrderedDict
from typing import Any, Callable, Dict

from agno.tools.function import Function
from agno.utils.log import logger


class Toolkit:
    def __init__(self, name: str = "toolkit"):
        """Initialize a new Toolkit.

        Args:
            name: A descriptive name for the toolkit
        """
        self.name: str = name
        self.functions: Dict[str, Function] = OrderedDict()

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
            )
            self.functions[f.name] = f
            logger.debug(f"Function: {f.name} registered with {self.name}")
        except Exception as e:
            logger.warning(f"Failed to create Function for: {function.__name__}")
            raise e

    def instructions(self) -> str:
        return ""

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name} functions={list(self.functions.keys())}>"

    def __str__(self):
        return self.__repr__()
