import inspect
from unittest.mock import Mock

from agno.agent import Agent
from agno.models.openai import OpenAIChat


def _async_stream():
    async def _gen():
        yield "event"

    return _gen()


def test_areason_delegation_returns_async_iterator(mocker):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    areason_mock = mocker.patch("agno.agent._response.areason", side_effect=lambda *args, **kwargs: _async_stream())

    result = agent._areason(run_response=Mock(), run_messages=Mock())

    assert not inspect.iscoroutine(result)
    assert hasattr(result, "__aiter__")
    areason_mock.assert_called_once()


def test_arun_stream_delegation_returns_async_iterator(mocker):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    arun_stream_mock = mocker.patch(
        "agno.agent._run.arun_stream_impl",
        side_effect=lambda *args, **kwargs: _async_stream(),
    )

    result = agent._arun_stream(
        run_response=Mock(),
        run_context=Mock(),
        session_id="test-session",
    )

    assert not inspect.iscoroutine(result)
    assert hasattr(result, "__aiter__")
    arun_stream_mock.assert_called_once()


def test_acontinue_run_stream_delegation_returns_async_iterator(mocker):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    acontinue_stream_mock = mocker.patch(
        "agno.agent._run.acontinue_run_stream_impl",
        side_effect=lambda *args, **kwargs: _async_stream(),
    )

    result = agent._acontinue_run_stream(
        session_id="test-session",
        run_context=Mock(),
    )

    assert not inspect.iscoroutine(result)
    assert hasattr(result, "__aiter__")
    acontinue_stream_mock.assert_called_once()
