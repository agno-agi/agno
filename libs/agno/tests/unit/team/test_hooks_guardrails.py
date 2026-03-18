"""Tests for guardrail behavior in team hook execution under background mode.

Mirrors the agent hook tests to verify parity between agent/_hooks.py and team/_hooks.py.
"""

from typing import Any, List, Union
from unittest.mock import MagicMock

import pytest

from agno.exceptions import InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run import RunContext
from agno.run.team import TeamRunInput
from agno.team._hooks import (
    _aexecute_post_hooks,
    _aexecute_pre_hooks,
    _execute_post_hooks,
    _execute_pre_hooks,
)
from agno.utils.hooks import normalize_pre_hooks


class BlockingGuardrail(BaseGuardrail):
    def check(self, run_input: Union[TeamRunInput, Any]) -> None:
        raise InputCheckError("blocked by guardrail")

    async def async_check(self, run_input: Union[TeamRunInput, Any]) -> None:
        raise InputCheckError("blocked by guardrail (async)")


class OutputBlockingGuardrail(BaseGuardrail):
    def check(self, **kwargs: Any) -> None:
        raise OutputCheckError("blocked output")

    async def async_check(self, **kwargs: Any) -> None:
        raise OutputCheckError("blocked output (async)")


class PassthroughGuardrail(BaseGuardrail):
    def __init__(self):
        self.call_count = 0

    def check(self, **kwargs: Any) -> None:
        self.call_count += 1

    async def async_check(self, **kwargs: Any) -> None:
        self.call_count += 1


def _make_team(run_hooks_in_background: bool = True) -> MagicMock:
    team = MagicMock()
    team._run_hooks_in_background = run_hooks_in_background
    team.debug_mode = False
    team.events_to_skip = None
    team.store_events = False
    return team


def _make_background_tasks() -> MagicMock:
    bt = MagicMock()
    bt.tasks: List = []

    def add_task(fn, **kwargs):
        bt.tasks.append((fn, kwargs))

    bt.add_task = add_task
    return bt


def _make_session() -> MagicMock:
    return MagicMock()


def _make_run_context() -> RunContext:
    return RunContext(run_id="r1", session_id="s1", session_state={}, metadata={"key": "val"})


def _make_run_input() -> TeamRunInput:
    return TeamRunInput(input_content="test input")


class TestTeamPreHookGuardrailInBackground:
    def test_guardrail_runs_sync_in_global_background_mode(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        hooks = normalize_pre_hooks([guardrail], async_mode=False)

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            list(
                _execute_pre_hooks(
                    team=team,
                    hooks=hooks,
                    run_response=MagicMock(),
                    run_input=_make_run_input(),
                    session=_make_session(),
                    run_context=_make_run_context(),
                    background_tasks=bt,
                )
            )
        assert len(bt.tasks) == 0

    @pytest.mark.asyncio
    async def test_async_guardrail_runs_sync_in_global_background_mode(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        hooks = normalize_pre_hooks([guardrail], async_mode=True)

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            async for _ in _aexecute_pre_hooks(
                team=team,
                hooks=hooks,
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            ):
                pass
        assert len(bt.tasks) == 0

    def test_non_guardrail_hook_goes_to_background(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()

        def plain_hook(**kwargs):
            pass

        list(
            _execute_pre_hooks(
                team=team,
                hooks=[plain_hook],
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            )
        )
        assert len(bt.tasks) == 1


class TestTeamPostHookGuardrailInBackground:
    def test_output_guardrail_runs_sync_in_global_background_mode(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = OutputBlockingGuardrail()

        with pytest.raises(OutputCheckError, match="blocked output"):
            list(
                _execute_post_hooks(
                    team=team,
                    hooks=[guardrail.check],
                    run_output=MagicMock(),
                    session=_make_session(),
                    run_context=_make_run_context(),
                    background_tasks=bt,
                )
            )
        assert len(bt.tasks) == 0

    @pytest.mark.asyncio
    async def test_async_output_guardrail_runs_sync_in_global_background_mode(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = OutputBlockingGuardrail()

        with pytest.raises(OutputCheckError, match="blocked output"):
            async for _ in _aexecute_post_hooks(
                team=team,
                hooks=[guardrail.async_check],
                run_output=MagicMock(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            ):
                pass
        assert len(bt.tasks) == 0


class TestTeamMixedHookOrdering:
    def test_plain_hook_before_guardrail_not_queued_on_rejection(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=False)

        def plain_hook(**kwargs):
            pass

        hooks = [plain_hook] + guardrail_hooks

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            list(
                _execute_pre_hooks(
                    team=team,
                    hooks=hooks,
                    run_response=MagicMock(),
                    run_input=_make_run_input(),
                    session=_make_session(),
                    run_context=_make_run_context(),
                    background_tasks=bt,
                )
            )
        assert len(bt.tasks) == 0

    @pytest.mark.asyncio
    async def test_async_plain_hook_before_guardrail_not_queued_on_rejection(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=True)

        def plain_hook(**kwargs):
            pass

        hooks = [plain_hook] + guardrail_hooks

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            async for _ in _aexecute_pre_hooks(
                team=team,
                hooks=hooks,
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            ):
                pass
        assert len(bt.tasks) == 0

    def test_post_hook_plain_before_guardrail_not_queued_on_rejection(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = OutputBlockingGuardrail()

        def plain_hook(**kwargs):
            pass

        hooks = [plain_hook, guardrail.check]

        with pytest.raises(OutputCheckError, match="blocked output"):
            list(
                _execute_post_hooks(
                    team=team,
                    hooks=hooks,
                    run_output=MagicMock(),
                    session=_make_session(),
                    run_context=_make_run_context(),
                    background_tasks=bt,
                )
            )
        assert len(bt.tasks) == 0


class TestTeamPostHookBackgroundEnqueue:
    def test_non_guardrail_post_hook_goes_to_background(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()

        def plain_post_hook(**kwargs):
            pass

        list(
            _execute_post_hooks(
                team=team,
                hooks=[plain_post_hook],
                run_output=MagicMock(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            )
        )
        assert len(bt.tasks) == 1

    @pytest.mark.asyncio
    async def test_async_non_guardrail_post_hook_goes_to_background(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()

        def plain_post_hook(**kwargs):
            pass

        async for _ in _aexecute_post_hooks(
            team=team,
            hooks=[plain_post_hook],
            run_output=MagicMock(),
            session=_make_session(),
            run_context=_make_run_context(),
            background_tasks=bt,
        ):
            pass
        assert len(bt.tasks) == 1


class MutatingGuardrail(BaseGuardrail):
    def check(self, run_input: Union[TeamRunInput, Any], **kwargs: Any) -> None:
        run_input.input_content = "[REDACTED]"

    async def async_check(self, run_input: Union[TeamRunInput, Any], **kwargs: Any) -> None:
        run_input.input_content = "[REDACTED]"


class CrashingGuardrail(BaseGuardrail):
    def check(self, **kwargs: Any) -> None:
        raise RuntimeError("unexpected internal error")

    async def async_check(self, **kwargs: Any) -> None:
        raise RuntimeError("unexpected internal error")


class TestTeamMutatingGuardrailBackground:
    def test_bg_hooks_receive_post_mutation_data(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = MutatingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=False)

        def spy_hook(run_input, **kwargs):
            pass

        hooks = guardrail_hooks + [spy_hook]

        list(
            _execute_pre_hooks(
                team=team,
                hooks=hooks,
                run_response=MagicMock(),
                run_input=TeamRunInput(input_content="sensitive data"),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            )
        )
        assert len(bt.tasks) == 1
        _, task_kwargs = bt.tasks[0]
        assert task_kwargs["run_input"].input_content == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_async_bg_hooks_receive_post_mutation_data(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = MutatingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=True)

        def spy_hook(run_input, **kwargs):
            pass

        hooks = guardrail_hooks + [spy_hook]

        async for _ in _aexecute_pre_hooks(
            team=team,
            hooks=hooks,
            run_response=MagicMock(),
            run_input=TeamRunInput(input_content="sensitive data"),
            session=_make_session(),
            run_context=_make_run_context(),
            background_tasks=bt,
        ):
            pass
        assert len(bt.tasks) == 1
        _, task_kwargs = bt.tasks[0]
        assert task_kwargs["run_input"].input_content == "[REDACTED]"


class TestTeamCrashingGuardrailBackground:
    def test_unexpected_exception_logged_not_propagated(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = CrashingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=False)

        def plain_hook(**kwargs):
            pass

        hooks = guardrail_hooks + [plain_hook]

        list(
            _execute_pre_hooks(
                team=team,
                hooks=hooks,
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            )
        )
        assert len(bt.tasks) == 1

    @pytest.mark.asyncio
    async def test_async_unexpected_exception_logged_not_propagated(self):
        team = _make_team(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = CrashingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=True)

        def plain_hook(**kwargs):
            pass

        hooks = guardrail_hooks + [plain_hook]

        async for _ in _aexecute_pre_hooks(
            team=team,
            hooks=hooks,
            run_response=MagicMock(),
            run_input=_make_run_input(),
            session=_make_session(),
            run_context=_make_run_context(),
            background_tasks=bt,
        ):
            pass
        assert len(bt.tasks) == 1


class TestTeamMetadataInjection:
    def test_metadata_from_run_context_passed_to_hooks(self):
        team = _make_team(run_hooks_in_background=False)
        captured_args = {}

        def spy_hook(**kwargs):
            captured_args.update(kwargs)

        run_context = _make_run_context()
        run_context.metadata = {"env": "test", "version": "2.5"}

        list(
            _execute_pre_hooks(
                team=team,
                hooks=[spy_hook],
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=_make_session(),
                run_context=run_context,
            )
        )
        assert captured_args.get("metadata") == {"env": "test", "version": "2.5"}
