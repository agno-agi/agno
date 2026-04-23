"""Regression tests for #7604 – InputCheckError/OutputCheckError raised inside a
guardrail pre-hook must propagate out of agent.run() / arun() so user code can
catch them directly.

Previously the exceptions were caught internally and silently converted to a
RunOutput with status=error, making `except InputCheckError` unreachable.
"""

from typing import Any, AsyncIterator, Iterator, Union
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from agno.agent.agent import Agent
from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunInput, RunOutput, RunStatus
from agno.run.team import TeamRunInput
from agno.utils.hooks import normalize_pre_hooks


# ---------------------------------------------------------------------------
# Minimal guardrails
# ---------------------------------------------------------------------------


class AlwaysBlockGuardrail(BaseGuardrail):
    """Guardrail that unconditionally raises InputCheckError."""

    def check(self, run_input: Union[RunInput, TeamRunInput], **kwargs) -> None:
        raise InputCheckError("blocked by guardrail", check_trigger=CheckTrigger.INPUT_NOT_ALLOWED)

    async def async_check(self, run_input: Union[RunInput, TeamRunInput], **kwargs) -> None:
        raise InputCheckError(
            "blocked by guardrail (async)", check_trigger=CheckTrigger.INPUT_NOT_ALLOWED
        )


# ---------------------------------------------------------------------------
# Minimal mock model (needed so the Agent can be constructed)
# ---------------------------------------------------------------------------


class _DummyModel(Model):
    """A no-op model that should never be reached when the guardrail blocks."""

    def __init__(self):
        super().__init__(id="dummy", name="dummy", provider="test")
        self.instructions = None
        self._resp = ModelResponse(
            content="should not reach here",
            role="assistant",
            response_usage=MessageMetrics(),
        )
        self.response = Mock(return_value=self._resp)
        self.aresponse = AsyncMock(return_value=self._resp)

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._resp

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return await self.aresponse(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._resp

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._resp
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._resp

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._resp


# ---------------------------------------------------------------------------
# Helpers for hook-layer tests
# ---------------------------------------------------------------------------


def _make_mock_agent(pre_hooks=None):
    """Return a MagicMock Agent with just enough attributes for _hooks execution."""
    agent = MagicMock()
    agent._run_hooks_in_background = False
    agent.debug_mode = False
    agent.events_to_skip = []
    agent.store_events = False
    agent.pre_hooks = pre_hooks
    agent.post_hooks = None
    return agent


def _make_run_context():
    return RunContext(run_id="r1", session_id="s1", session_state={}, metadata={})


def _make_run_input():
    return RunInput(input_content="hello")


# ---------------------------------------------------------------------------
# Tests for _hooks.execute_pre_hooks (the hook-layer, already re-raises)
# ---------------------------------------------------------------------------


class TestHookLayerPropagation:
    """Confirm the hook layer itself propagates InputCheckError (sanity check)."""

    def test_execute_pre_hooks_raises_input_check_error(self):
        from agno.agent._hooks import execute_pre_hooks

        agent = _make_mock_agent()
        guardrail = AlwaysBlockGuardrail()
        hooks = normalize_pre_hooks([guardrail], async_mode=False)

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            list(
                execute_pre_hooks(
                    agent=agent,
                    hooks=hooks,
                    run_response=MagicMock(),
                    run_input=_make_run_input(),
                    session=MagicMock(),
                    run_context=_make_run_context(),
                )
            )

    @pytest.mark.asyncio
    async def test_aexecute_pre_hooks_raises_input_check_error(self):
        from agno.agent._hooks import aexecute_pre_hooks

        agent = _make_mock_agent()
        guardrail = AlwaysBlockGuardrail()
        hooks = normalize_pre_hooks([guardrail], async_mode=True)

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            async for _ in aexecute_pre_hooks(
                agent=agent,
                hooks=hooks,
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=MagicMock(),
                run_context=_make_run_context(),
            ):
                pass


# ---------------------------------------------------------------------------
# Tests for plain pre_hook function raising InputCheckError (#7604)
# Regression: when a plain function (not a BaseGuardrail subclass) raises
# InputCheckError, the exception must still propagate out of agent.run().
# ---------------------------------------------------------------------------


class TestPlainHookRaisesInputCheckError:
    """Regression test for #7604.

    A plain callable passed as a pre_hook that raises InputCheckError must
    propagate out of the execute_pre_hooks generator so that callers can catch it.
    Previously the exception was swallowed at the _run() level.
    """

    def test_plain_pre_hook_raises_input_check_error_propagates(self):
        from agno.agent._hooks import execute_pre_hooks

        agent = _make_mock_agent()

        def blocking_hook(run_input, **kwargs):
            raise InputCheckError("rejected by plain hook")

        with pytest.raises(InputCheckError, match="rejected by plain hook"):
            list(
                execute_pre_hooks(
                    agent=agent,
                    hooks=[blocking_hook],
                    run_response=MagicMock(),
                    run_input=_make_run_input(),
                    session=MagicMock(),
                    run_context=_make_run_context(),
                )
            )

    @pytest.mark.asyncio
    async def test_async_plain_pre_hook_raises_input_check_error_propagates(self):
        from agno.agent._hooks import aexecute_pre_hooks

        agent = _make_mock_agent()

        async def async_blocking_hook(run_input, **kwargs):
            raise InputCheckError("rejected by async plain hook")

        with pytest.raises(InputCheckError, match="rejected by async plain hook"):
            async for _ in aexecute_pre_hooks(
                agent=agent,
                hooks=[async_blocking_hook],
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=MagicMock(),
                run_context=_make_run_context(),
            ):
                pass


# ---------------------------------------------------------------------------
# END-TO-END tests: agent.run() / agent.arun() with a blocking guardrail
# These exercise the actual _run.py code paths that were fixed (#7604).
# Reverting the _run.py changes would cause these tests to FAIL.
# ---------------------------------------------------------------------------


class TestEndToEndInputCheckErrorPropagation:
    """End-to-end tests verifying InputCheckError propagates through agent.run()
    and agent.arun() — the actual fix site in _run.py.

    Before the fix, these exceptions were caught in the try/except blocks inside
    _run(), _arun(), etc. and converted to a RunOutput with status=error. The
    user's `except InputCheckError` block was unreachable.
    """

    def test_agent_run_raises_input_check_error(self):
        """Sync non-stream: agent.run() must propagate InputCheckError."""
        agent = Agent(
            model=_DummyModel(),
            pre_hooks=[AlwaysBlockGuardrail()],
        )

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            agent.run("hello")

    @pytest.mark.asyncio
    async def test_agent_arun_raises_input_check_error(self):
        """Async non-stream: agent.arun() must propagate InputCheckError."""
        agent = Agent(
            model=_DummyModel(),
            pre_hooks=[AlwaysBlockGuardrail()],
        )

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            await agent.arun("hello")

    def test_agent_run_stream_raises_input_check_error(self):
        """Sync stream: consuming agent.run(stream=True) must propagate
        InputCheckError after yielding the error event."""
        agent = Agent(
            model=_DummyModel(),
            pre_hooks=[AlwaysBlockGuardrail()],
        )

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            for _ in agent.run("hello", stream=True):
                pass

    @pytest.mark.asyncio
    async def test_agent_arun_stream_raises_input_check_error(self):
        """Async stream: consuming agent.arun(stream=True) must propagate
        InputCheckError after yielding the error event."""
        agent = Agent(
            model=_DummyModel(),
            pre_hooks=[AlwaysBlockGuardrail()],
        )

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            async for _ in agent.arun("hello", stream=True):
                pass

    def test_agent_run_plain_hook_raises_input_check_error(self):
        """Sync non-stream with a plain callable pre_hook (not a BaseGuardrail)."""

        def blocking_hook(run_input, **kwargs):
            raise InputCheckError("plain hook blocked")

        agent = Agent(
            model=_DummyModel(),
            pre_hooks=[blocking_hook],
        )

        with pytest.raises(InputCheckError, match="plain hook blocked"):
            agent.run("hello")

    @pytest.mark.asyncio
    async def test_agent_arun_plain_hook_raises_input_check_error(self):
        """Async non-stream with a plain callable pre_hook (not a BaseGuardrail)."""

        async def async_blocking_hook(run_input, **kwargs):
            raise InputCheckError("async plain hook blocked")

        agent = Agent(
            model=_DummyModel(),
            pre_hooks=[async_blocking_hook],
        )

        with pytest.raises(InputCheckError, match="async plain hook blocked"):
            await agent.arun("hello")
