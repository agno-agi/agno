"""Show how to use a tool execution hook, to run logic before and after a tool is called."""

from typing import Any, Callable, Dict

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from agno.utils.log import logger

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def logger_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    # Pre-hook logic: this runs before the tool is called
    logger.info(f"Running {function_name} with arguments {arguments}")

    # Call the tool
    result = function_call(**arguments)

    # Post-hook logic: this runs after the tool is called
    logger.info(f"Result of {function_name} is {result}")
    return result


agent = Agent(
    model=OpenAIChat(id="gpt-4o"), tools=[WebSearchTools()], tool_hooks=[logger_hook]
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What's happening in the world?", stream=True, markdown=True)

    # ---------------------------------------------------------------------------
    # Async Variant
    # ---------------------------------------------------------------------------

    """Show how to use a tool execution hook with async functions, to run logic before and after a tool is called."""

    import asyncio
    from inspect import iscoroutinefunction
    from typing import Any, Callable, Dict

    from agno.agent import Agent
    from agno.tools.websearch import WebSearchTools
    from agno.utils.log import logger

    async def logger_hook(
        function_name: str, function_call: Callable, arguments: Dict[str, Any]
    ):
        # Pre-hook logic: this runs before the tool is called
        logger.info(f"Running {function_name} with arguments {arguments}")

        # Call the tool
        if iscoroutinefunction(function_call):
            result = await function_call(**arguments)
        else:
            result = function_call(**arguments)

        # Post-hook logic: this runs after the tool is called
        logger.info(f"Result of {function_name} is {result}")
        return result

    agent = Agent(tools=[WebSearchTools()], tool_hooks=[logger_hook])

    asyncio.run(agent.aprint_response("What is currently trending on Twitter?"))
