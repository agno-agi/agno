import inspect
from unittest.mock import Mock

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat


def _async_stream():
    async def _gen():
        yield "event"

    return _gen()


@pytest.mark.parametrize(
    "target,method_name,kwargs",
    [
        ("agno.agent._response.areason", "_areason", {"run_response": Mock(), "run_messages": Mock()}),
        (
            "agno.agent._run.arun_stream_impl",
            "_arun_stream",
            {"run_response": Mock(), "run_context": Mock(), "session_id": "test-session"},
        ),
        (
            "agno.agent._run.acontinue_run_stream_impl",
            "_acontinue_run_stream",
            {"session_id": "test-session", "run_context": Mock()},
        ),
        (
            "agno.agent._hooks.aexecute_pre_hooks",
            "_aexecute_pre_hooks",
            {
                "hooks": [],
                "run_response": Mock(),
                "run_input": Mock(),
                "run_context": Mock(),
                "session": Mock(),
            },
        ),
        (
            "agno.agent._hooks.aexecute_post_hooks",
            "_aexecute_post_hooks",
            {
                "hooks": [],
                "run_output": Mock(),
                "run_context": Mock(),
                "session": Mock(),
            },
        ),
        (
            "agno.agent._response.ahandle_reasoning_stream",
            "_ahandle_reasoning_stream",
            {"run_response": Mock(), "run_messages": Mock()},
        ),
        (
            "agno.agent._response.aparse_response_with_parser_model_stream",
            "_aparse_response_with_parser_model_stream",
            {"session": Mock(), "run_response": Mock()},
        ),
        (
            "agno.agent._response.agenerate_response_with_output_model_stream",
            "_agenerate_response_with_output_model_stream",
            {"session": Mock(), "run_response": Mock(), "run_messages": Mock()},
        ),
        (
            "agno.agent._hooks.ahandle_agent_run_paused_stream",
            "_ahandle_agent_run_paused_stream",
            {"run_response": Mock(), "session": Mock()},
        ),
        (
            "agno.agent._tools.arun_tool",
            "_arun_tool",
            {"run_response": Mock(), "run_messages": Mock(), "tool": Mock()},
        ),
        (
            "agno.agent._tools.ahandle_tool_call_updates_stream",
            "_ahandle_tool_call_updates_stream",
            {"run_response": Mock(), "run_messages": Mock(), "tools": []},
        ),
        (
            "agno.agent._response.ahandle_model_response_stream",
            "_ahandle_model_response_stream",
            {"session": Mock(), "run_response": Mock(), "run_messages": Mock()},
        ),
    ],
)
def test_async_generator_delegations_return_async_iterators(mocker, target, method_name, kwargs):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    delegated_mock = mocker.patch(target, side_effect=lambda *args, **kwargs: _async_stream())

    result = getattr(agent, method_name)(**kwargs)

    assert not inspect.iscoroutine(result)
    assert hasattr(result, "__aiter__")
    delegated_mock.assert_called_once()
