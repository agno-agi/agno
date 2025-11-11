from typing import Any, Callable, Dict
from unittest.mock import patch

import pytest

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.tools.decorator import tool
from agno.utils.log import logger

# --- Hooks Definition ---


def logger_hook(
    function_name: str,
    function_call: Callable[..., Any],
    arguments: Dict[str, Any],
) -> Any:
    logger.info(f"HOOK PRE: Calling {function_name} with args {arguments}")
    result = function_call(**arguments)
    logger.info(f"HOOK POST: {function_name} returned {result}")
    return result


def confirmation_hook(
    function_name: str,
    function_call: Callable[..., Any],
    arguments: Dict[str, Any],
) -> Any:
    if function_name == "add":
        logger.info("This tool is not allowed to be called")
        return
    logger.info("This tool is allowed to be called")
    return function_call(**arguments)


# --- Tools Definition ---


@tool()
def add(a: int, b: int) -> int:
    return a + b


@tool(tool_hooks=[logger_hook])
def sub(a: int, b: int) -> int:
    return a - b


@tool(tool_hooks=[confirmation_hook])
def mul(a: int, b: int) -> int:
    return a * b


# --- Test Cases ---


def test_logger_hook_invocation_sub_tool():
    agent = Agent(tools=[sub])

    with patch.object(type(logger), "info", wraps=logger.info) as mock_info:
        response: RunOutput = agent.run("Compute 6 - 5")

        assert response.tools is not None
        assert response.tools[0].tool_name == "sub"
        assert response.tools[0].result == "1"

        mock_info.assert_any_call("HOOK PRE: Calling sub with args {'a': 6, 'b': 5}")
        mock_info.assert_any_call("HOOK POST: sub returned 1")


def test_confirmation_hook_blocks_add_tool():
    agent = Agent(tools=[add], tool_hooks=[confirmation_hook])

    with patch.object(type(logger), "info", wraps=logger.info) as mock_info:
        agent.run("Compute 4 + 5")

        mock_info.assert_any_call("This tool is not allowed to be called")


def test_confirmation_hook_allows_mul_tool():
    agent = Agent(tools=[mul], tool_hooks=[confirmation_hook])

    with patch.object(type(logger), "info", wraps=logger.info) as mock_info:
        response: RunOutput = agent.run("Compute 4 * 5")

        mock_info.assert_any_call("This tool is allowed to be called")
        assert response.tools is not None
        assert response.tools[0].tool_name == "mul"
        assert response.tools[0].result == "20"


def test_logger_hook_invocation_add_tool():
    agent = Agent(tools=[add], tool_hooks=[logger_hook])

    with patch.object(type(logger), "info", wraps=logger.info) as mock_info:
        response: RunOutput = agent.run("Compute 4 + 5")

        assert response.tools is not None
        assert response.tools[0].tool_name == "add"
        assert response.tools[0].result == "9"

        mock_info.assert_any_call("HOOK PRE: Calling add with args {'a': 4, 'b': 5}")
        mock_info.assert_any_call("HOOK POST: add returned 9")


def test_logger_hook_invocation_mul_tool():
    agent = Agent(tools=[mul], tool_hooks=[logger_hook])

    with patch.object(type(logger), "info", wraps=logger.info) as mock_info:
        response: RunOutput = agent.run("Compute 3 * 3")

        assert response.tools is not None
        assert response.tools[0].tool_name == "mul"
        assert response.tools[0].result == "9"

        mock_info.assert_any_call("HOOK PRE: Calling mul with args {'a': 3, 'b': 3}")
        mock_info.assert_any_call("HOOK POST: mul returned 9")


def test_logger_and_confirmation_hooks_combined():
    agent = Agent(
        tools=[add, mul],
        tool_hooks=[logger_hook, confirmation_hook],  # Logger outer, confirmation inner
    )

    with patch.object(type(logger), "info", wraps=logger.info) as mock_info:
        agent.run("Compute 2 + 3 and 4 * 5")

        # add tool should be blocked by confirmation_hook
        mock_info.assert_any_call("This tool is not allowed to be called")

        # mul tool should be allowed and logged
        mock_info.assert_any_call("This tool is allowed to be called")
        mock_info.assert_any_call("HOOK PRE: Calling mul with args {'a': 4, 'b': 5}")
        mock_info.assert_any_call("HOOK POST: mul returned 20")


@pytest.mark.asyncio
async def test_logger_and_confirmation_hooks_combined_async():
    agent = Agent(
        tools=[add, mul],
        tool_hooks=[logger_hook, confirmation_hook],  # Logger outer, confirmation inner
    )

    with patch.object(type(logger), "info", wraps=logger.info) as mock_info:
        await agent.arun("Compute 2 + 3 and 4 * 5")

        # Check that add tool was blocked by confirmation_hook
        mock_info.assert_any_call("This tool is not allowed to be called")

        # Check that mul tool was allowed and logged
        mock_info.assert_any_call("This tool is allowed to be called")
        mock_info.assert_any_call("HOOK PRE: Calling mul with args {'a': 4, 'b': 5}")
        mock_info.assert_any_call("HOOK POST: mul returned 20")
