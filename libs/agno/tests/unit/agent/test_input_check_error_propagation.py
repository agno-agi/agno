"""Regression tests for #7604 – InputCheckError/OutputCheckError raised inside a
guardrail pre-hook must propagate out of agent.run() / arun() so user code can
catch them directly.

Previously the exceptions were caught internally and silently converted to a
RunOutput with status=error, making `except InputCheckError` unreachable.
"""

from typing import Union
from unittest.mock import MagicMock, patch

import pytest

from agno.agent._run import _run
from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail
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
# Helpers
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
