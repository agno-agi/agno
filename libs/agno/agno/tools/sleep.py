import time

from agno.tools import Toolkit
from agno.utils.log import log_info


class SleepTools(Toolkit):
    def __init__(self, **kwargs):
        super().__init__(name="sleep", **kwargs)

        self.register(self.sleep)

    def sleep(self, seconds: int) -> str:
        """Use this function to sleep for a given number of seconds."""
        log_info(f"Sleeping for {seconds} seconds")
        time.sleep(seconds)
        log_info(f"Awake after {seconds} seconds")
        return f"Slept for {seconds} seconds"
