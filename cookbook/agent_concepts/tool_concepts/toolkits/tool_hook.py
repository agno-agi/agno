"""Show how to use a tool execution hook, to run logic before and after a tool is called."""

from typing import Any, Callable, Dict

from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.log import logger


def logger_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    # Pre-hook logic: this runs before the tool is called
    logger.info(f"Running {function_name} with arguments {arguments}")

    # Call the tool
    result = function_call(**arguments)

    # Post-hook logic: this runs after the tool is called
    logger.info(f"Result of {function_name} is {result}")
    return result


agent = Agent(tools=[DuckDuckGoTools()], tool_hooks=[logger_hook])

agent.print_response("What is currently trending on Twitter?")
