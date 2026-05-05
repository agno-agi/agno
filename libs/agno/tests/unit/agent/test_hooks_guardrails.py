"""Tests for guardrail behavior in hook execution under background mode."""

from typing import Any, List, Union
from unittest.mock import MagicMock

import pytest

from agno.agent._hooks import (
    aexecute_post_hooks,
    aexecute_pre_hooks,
    execute_post_hooks,
    execute_pre_hooks,
)
from agno.exceptions import InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run import RunContext
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput
from agno.utils.hooks import is_guardrail_hook, normalize_pre_hooks


class BlockingGuardrail(BaseGuardrail):
    """Guardrail that raises InputCheckError."""

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        raise InputCheckError("blocked by guardrail")

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        raise InputCheckError("blocked by guardrail (async)")


class OutputBlockingGuardrail(BaseGuardrail):
    """Guardrail that raises OutputCheckError."""

    def check(self, **kwargs: Any) -> None:
        raise OutputCheckError("blocked output")

    async def async_check(self, **kwargs: Any) -> None:
        raise OutputCheckError("blocked output (async)")


class PassthroughGuardrail(BaseGuardrail):
    """Guardrail that passes (no error)."""

    def __init__(self):
        self.call_count = 0

    def check(self, **kwargs: Any) -> None:
        self.call_count += 1

    async def async_check(self, **kwargs: Any) -> None:
        self.call_count += 1


def _make_agent(run_hooks_in_background: bool = True) -> MagicMock:
    agent = MagicMock()
    agent._run_hooks_in_background = run_hooks_in_background
    agent.debug_mode = False
    agent.events_to_skip = None
    agent.store_events = False
    return agent


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


def _make_run_input() -> RunInput:
    return RunInput(input_content="test input")


class TestIsGuardrailHook:
    def test_bound_guardrail_check_detected(self):
        g = PassthroughGuardrail()
        assert is_guardrail_hook(g.check) is True
        assert is_guardrail_hook(g.async_check) is True

    def test_plain_function_not_detected(self):
        def plain_hook(**kwargs):
            pass

        assert is_guardrail_hook(plain_hook) is False

    def test_normalize_pre_hooks_produces_guardrail_hooks(self):
        g = BlockingGuardrail()
        hooks = normalize_pre_hooks([g], async_mode=False)
        assert hooks is not None
        assert is_guardrail_hook(hooks[0]) is True


class TestPreHookGuardrailInBackground:
    def test_guardrail_runs_sync_in_global_background_mode(self):
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        hooks = normalize_pre_hooks([guardrail], async_mode=False)

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            list(
                execute_pre_hooks(
                    agent=agent,
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
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        hooks = normalize_pre_hooks([guardrail], async_mode=True)

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            async for _ in aexecute_pre_hooks(
                agent=agent,
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
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()

        def plain_hook(**kwargs):
            pass

        hooks = [plain_hook]

        list(
            execute_pre_hooks(
                agent=agent,
                hooks=hooks,
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            )
        )
        assert len(bt.tasks) == 1


class TestPostHookGuardrailInBackground:
    def test_output_guardrail_runs_sync_in_global_background_mode(self):
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = OutputBlockingGuardrail()
        hooks = [guardrail.check]

        with pytest.raises(OutputCheckError, match="blocked output"):
            list(
                execute_post_hooks(
                    agent=agent,
                    hooks=hooks,
                    run_output=MagicMock(),
                    session=_make_session(),
                    run_context=_make_run_context(),
                    background_tasks=bt,
                )
            )
        assert len(bt.tasks) == 0

    @pytest.mark.asyncio
    async def test_async_output_guardrail_runs_sync_in_global_background_mode(self):
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = OutputBlockingGuardrail()
        hooks = [guardrail.async_check]

        with pytest.raises(OutputCheckError, match="blocked output"):
            async for _ in aexecute_post_hooks(
                agent=agent,
                hooks=hooks,
                run_output=MagicMock(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            ):
                pass
        assert len(bt.tasks) == 0

    def test_non_guardrail_post_hook_goes_to_background(self):
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()

        def plain_post_hook(**kwargs):
            pass

        hooks = [plain_post_hook]
        list(
            execute_post_hooks(
                agent=agent,
                hooks=hooks,
                run_output=MagicMock(),
                session=_make_session(),
                run_context=_make_run_context(),
                background_tasks=bt,
            )
        )
        assert len(bt.tasks) == 1


class TestMixedHookOrdering:
    """Tests for hook ordering: non-guardrail hooks should NOT be queued if a later guardrail rejects."""

    def test_plain_hook_before_guardrail_not_queued_on_rejection(self):
        """When a plain hook appears before a guardrail, the buffer-and-flush
        pattern ensures the plain hook is NOT queued if the guardrail rejects.
        """
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=False)

        def plain_hook(**kwargs):
            pass

        # plain_hook BEFORE guardrail
        hooks = [plain_hook] + guardrail_hooks

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            list(
                execute_pre_hooks(
                    agent=agent,
                    hooks=hooks,
                    run_response=MagicMock(),
                    run_input=_make_run_input(),
                    session=_make_session(),
                    run_context=_make_run_context(),
                    background_tasks=bt,
                )
            )
        assert len(bt.tasks) == 0

    def test_plain_hook_after_guardrail_not_queued_on_rejection(self):
        """When a guardrail appears first, the exception prevents later hooks from queueing."""
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=False)

        def plain_hook(**kwargs):
            pass

        # guardrail BEFORE plain_hook — this ordering is safe
        hooks = guardrail_hooks + [plain_hook]

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            list(
                execute_pre_hooks(
                    agent=agent,
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
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = BlockingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=True)

        def plain_hook(**kwargs):
            pass

        hooks = [plain_hook] + guardrail_hooks

        with pytest.raises(InputCheckError, match="blocked by guardrail"):
            async for _ in aexecute_pre_hooks(
                agent=agent,
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
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = OutputBlockingGuardrail()

        def plain_hook(**kwargs):
            pass

        # plain_hook BEFORE guardrail
        hooks = [plain_hook, guardrail.check]

        with pytest.raises(OutputCheckError, match="blocked output"):
            list(
                execute_post_hooks(
                    agent=agent,
                    hooks=hooks,
                    run_output=MagicMock(),
                    session=_make_session(),
                    run_context=_make_run_context(),
                    background_tasks=bt,
                )
            )
        assert len(bt.tasks) == 0


class TestDebugModeFalse:
    def test_debug_mode_false_not_overridden_by_agent(self):
        agent = _make_agent()
        agent.debug_mode = True
        guardrail = PassthroughGuardrail()
        hooks = normalize_pre_hooks([guardrail], async_mode=False)

        captured_args = {}
        original_check = guardrail.check

        def spy_check(**kwargs):
            captured_args.update(kwargs)
            return original_check(**kwargs)

        hooks = [spy_check]

        list(
            execute_pre_hooks(
                agent=agent,
                hooks=hooks,
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=_make_session(),
                run_context=_make_run_context(),
                debug_mode=False,
            )
        )
        assert captured_args.get("debug_mode") is False


class TestMetadataInjection:
    def test_metadata_from_run_context_passed_to_hooks(self):
        agent = _make_agent(run_hooks_in_background=False)
        captured_args = {}

        def spy_hook(**kwargs):
            captured_args.update(kwargs)

        run_context = _make_run_context()
        run_context.metadata = {"env": "test", "version": "2.5"}

        list(
            execute_pre_hooks(
                agent=agent,
                hooks=[spy_hook],
                run_response=MagicMock(),
                run_input=_make_run_input(),
                session=_make_session(),
                run_context=run_context,
            )
        )
        assert captured_args.get("metadata") == {"env": "test", "version": "2.5"}


class MutatingGuardrail(BaseGuardrail):
    def check(self, run_input: Union[RunInput, TeamRunInput], **kwargs: Any) -> None:
        run_input.input_content = "[REDACTED]"

    async def async_check(self, run_input: Union[RunInput, TeamRunInput], **kwargs: Any) -> None:
        run_input.input_content = "[REDACTED]"


class CrashingGuardrail(BaseGuardrail):
    def check(self, **kwargs: Any) -> None:
        raise RuntimeError("unexpected internal error")

    async def async_check(self, **kwargs: Any) -> None:
        raise RuntimeError("unexpected internal error")


class TestMutatingGuardrailBackground:
    def test_bg_hooks_receive_post_mutation_data(self):
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = MutatingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=False)

        captured_input = {}

        def spy_hook(run_input, **kwargs):
            captured_input["content"] = run_input.input_content

        hooks = guardrail_hooks + [spy_hook]

        list(
            execute_pre_hooks(
                agent=agent,
                hooks=hooks,
                run_response=MagicMock(),
                run_input=RunInput(input_content="sensitive data"),
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
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = MutatingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=True)

        def spy_hook(run_input, **kwargs):
            pass

        hooks = guardrail_hooks + [spy_hook]

        async for _ in aexecute_pre_hooks(
            agent=agent,
            hooks=hooks,
            run_response=MagicMock(),
            run_input=RunInput(input_content="sensitive data"),
            session=_make_session(),
            run_context=_make_run_context(),
            background_tasks=bt,
        ):
            pass
        assert len(bt.tasks) == 1
        _, task_kwargs = bt.tasks[0]
        assert task_kwargs["run_input"].input_content == "[REDACTED]"


class TestCrashingGuardrailBackground:
    def test_unexpected_exception_logged_not_propagated(self):
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = CrashingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=False)

        def plain_hook(**kwargs):
            pass

        hooks = guardrail_hooks + [plain_hook]

        list(
            execute_pre_hooks(
                agent=agent,
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
        agent = _make_agent(run_hooks_in_background=True)
        bt = _make_background_tasks()
        guardrail = CrashingGuardrail()
        guardrail_hooks = normalize_pre_hooks([guardrail], async_mode=True)

        def plain_hook(**kwargs):
            pass

        hooks = guardrail_hooks + [plain_hook]

        async for _ in aexecute_pre_hooks(
            agent=agent,
            hooks=hooks,
            run_response=MagicMock(),
            run_input=_make_run_input(),
            session=_make_session(),
            run_context=_make_run_context(),
            background_tasks=bt,
        ):
            pass
        assert len(bt.tasks) == 1


class TestPIIGuardrailTypeSafety:
    def test_mask_pii_masks_and_assigns_string(self):
        from agno.guardrails.pii import PIIDetectionGuardrail

        guardrail = PIIDetectionGuardrail(mask_pii=True, enable_email_check=True)
        run_input = RunInput(input_content="Contact me at user@example.com")
        guardrail.check(run_input)
        assert "@" not in run_input.input_content
        assert isinstance(run_input.input_content, str)

    @pytest.mark.asyncio
    async def test_async_mask_pii_masks_and_assigns_string(self):
        from agno.guardrails.pii import PIIDetectionGuardrail

        guardrail = PIIDetectionGuardrail(mask_pii=True, enable_email_check=True)
        run_input = RunInput(input_content="My SSN is 123-45-6789")
        await guardrail.async_check(run_input)
        assert "123-45-6789" not in run_input.input_content

    def test_detect_pii_raises_without_masking(self):
        from agno.guardrails.pii import PIIDetectionGuardrail

        guardrail = PIIDetectionGuardrail(mask_pii=False, enable_email_check=True)
        run_input = RunInput(input_content="Contact user@example.com")
        with pytest.raises(InputCheckError, match="Potential PII detected"):
            guardrail.check(run_input)
