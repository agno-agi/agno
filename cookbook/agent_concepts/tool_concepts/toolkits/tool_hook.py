from typing import Any, Callable, Dict

from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.log import logger


def logger_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    logger.info(f"Running {function_name} with arguments {arguments}")
    result = function_call(**arguments)

    logger.info(f"Result of {function_name} is {result}")
    return result


agent = Agent(tools=[DuckDuckGoTools()], tool_execution_hook=logger_hook)

agent.print_response("What is currently trending on Twitter?")
