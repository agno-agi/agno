import time
import warnings
from typing import Callable, List

from agno.tools import Toolkit
from agno.utils.log import log_info


class SleepTools(Toolkit):
    def __init__(
        self,
        sleep: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize SleepTools for pausing execution.

        Args:
            sleep: Enable the sleep tool. Defaults to True.
            all: Enable all tools. Defaults to False.
        """
        # Backwards compat for old param names
        if "enable_sleep" in kwargs:
            warnings.warn("enable_sleep is deprecated, use sleep", DeprecationWarning, stacklevel=2)
            sleep = kwargs.pop("enable_sleep")

        tools: List[Callable] = []
        if all or sleep:
            tools.append(self.sleep)

        super().__init__(name="sleep", tools=tools, **kwargs)

    def sleep(self, seconds: int) -> str:
        """Use this function to sleep for a given number of seconds."""
        log_info(f"Sleeping for {seconds} seconds")
        time.sleep(seconds)
        log_info(f"Awake after {seconds} seconds")
        return f"Slept for {seconds} seconds"
