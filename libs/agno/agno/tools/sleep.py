import time

from agno.tools import Toolkit
from agno.utils.log import log_info, log_warning


class SleepTools(Toolkit):
    def __init__(self, enable_sleep: bool = True, all: bool = False, **kwargs):
        tools = []
        if all or enable_sleep:
            tools.append(self.sleep)

        super().__init__(name="sleep", tools=tools, **kwargs)

    def sleep(self, seconds: float) -> str:
        """Use this function to sleep for a given number of seconds.

        Args:
            seconds: Number of seconds to sleep for. Must not be negative.
        """
        # Tool arguments arrive as JSON and are not validated against the declared
        # types, so a model can pass a string, and a negative duration would raise
        # out of time.sleep instead of answering the model.
        try:
            duration = float(seconds)
        except (TypeError, ValueError):
            log_warning(f"Invalid sleep duration: {seconds!r}")
            return f"Invalid sleep duration: {seconds!r}. Please provide a non-negative number of seconds."

        if duration < 0:
            log_warning(f"Invalid sleep duration: {duration}")
            return f"Invalid sleep duration: {duration}. Please provide a non-negative number of seconds."

        log_info(f"Sleeping for {duration} seconds")
        time.sleep(duration)
        log_info(f"Awake after {duration} seconds")
        return f"Slept for {duration} seconds"
