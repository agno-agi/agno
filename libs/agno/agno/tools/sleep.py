import asyncio
import time

from agno.tools import Toolkit
from agno.utils.log import log_info


class SleepTools(Toolkit):
    def __init__(self, enable_sleep: bool = True, all: bool = False, **kwargs):
        tools = []
        async_tools = []
        if all or enable_sleep:
            tools.append(self.sleep)
            async_tools.append((self.asleep, "sleep"))

        super().__init__(name="sleep", tools=tools, async_tools=async_tools, **kwargs)

    def sleep(self, seconds: int) -> str:
        """Use this function to sleep for a given number of seconds."""
        log_info(f"Sleeping for {seconds} seconds")
        time.sleep(seconds)
        log_info(f"Awake after {seconds} seconds")
        return f"Slept for {seconds} seconds"

    async def asleep(self, seconds: int) -> str:
        """Use this function to sleep for a given number of seconds."""
        log_info(f"Sleeping for {seconds} seconds")
        await asyncio.sleep(seconds)
        log_info(f"Awake after {seconds} seconds")
        return f"Slept for {seconds} seconds"
