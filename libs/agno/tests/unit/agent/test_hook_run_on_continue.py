"""Tests for @hook(run_on_continue=True) decorator behavior.

These tests verify that:
1. Regular hooks (no decorator) only run on initial run(), not continue_run()
2. Hooks with @hook(run_on_continue=True) run on BOTH run() and continue_run()
3. Guardrails always run on continue_run() for security
4. Multiple hooks with mixed configurations work correctly
"""

import pytest

import agno.agent._run as agent_run
import agno.agent._telemetry as agent_telemetry
from agno.agent.agent import Agent
from agno.exceptions import InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.hooks import hook
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext, RunStatus
from agno.run.agent import RunInput, RunOutput
from agno.run.messages import RunMessages
from agno.session import AgentSession


def _make_paused_run() -> RunOutput:
    return RunOutput(
        run_id="run-1",
        session_id="session-1",
        status=RunStatus.paused,
        input=RunInput(input_content="test question"),
        messages=[Message(role="user", content="test question")],
    )


def _make_run_context() -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1", user_id="user-1")


def _make_session() -> AgentSession:
    return AgentSession(session_id="session-1", user_id="user-1")


def _make_run_messages() -> RunMessages:
    return RunMessages(messages=[Message(role="user", content="test question")])


def _patch_model(monkeypatch):
    def fake_model(*args, **kwargs):
        return ModelResponse(role="assistant", content="response")

    monkeypatch.setattr(agent_run, "call_model_with_fallback", fake_model)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)


class TestHookRunOnContinue:
    """Tests for the @hook(run_on_continue=True) decorator."""

    def test_regular_hook_skipped_on_continue(self, monkeypatch):
        """Hooks without @hook(run_on_continue=True) are skipped on continue_run."""
        calls = []

        def regular_hook(run_input=None):
            calls.append("regular")

        agent = Agent(name="test-agent", pre_hooks=[regular_hook])
        _patch_model(monkeypatch)

        result = agent_run._continue_run(
            agent,
            run_response=_make_paused_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            session=_make_session(),
            tools=[],
            user_id="user-1",
        )

        assert result.status == RunStatus.completed
        assert calls == [], "regular hooks should be skipped on continue_run"

    def test_decorated_hook_runs_on_continue(self, monkeypatch):
        """Hooks with @hook(run_on_continue=True) run on continue_run."""
        calls = []

        @hook(run_on_continue=True)
        def security_hook(run_input=None):
            calls.append("security")

        agent = Agent(name="test-agent", pre_hooks=[security_hook])
        _patch_model(monkeypatch)

        result = agent_run._continue_run(
            agent,
            run_response=_make_paused_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            session=_make_session(),
            tools=[],
            user_id="user-1",
        )

        assert result.status == RunStatus.completed
        assert calls == ["security"], "decorated hooks should run on continue_run"

    def test_mixed_hooks_only_decorated_runs(self, monkeypatch):
        """With mixed hooks, only decorated ones run on continue_run."""
        calls = []

        def regular_hook(run_input=None):
            calls.append("regular")

        @hook(run_on_continue=True)
        def security_hook(run_input=None):
            calls.append("security")

        def another_regular(run_input=None):
            calls.append("another")

        @hook(run_on_continue=True)
        def audit_hook(run_input=None):
            calls.append("audit")

        agent = Agent(
            name="test-agent",
            pre_hooks=[regular_hook, security_hook, another_regular, audit_hook],
        )
        _patch_model(monkeypatch)

        result = agent_run._continue_run(
            agent,
            run_response=_make_paused_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            session=_make_session(),
            tools=[],
            user_id="user-1",
        )

        assert result.status == RunStatus.completed
        assert calls == ["security", "audit"], "only decorated hooks should run"

    def test_guardrail_always_runs_on_continue(self, monkeypatch):
        """Guardrails always run on continue_run for security."""
        calls = []

        class TestGuardrail(BaseGuardrail):
            def check(self, run_input=None):
                calls.append("guardrail")

            async def async_check(self, run_input=None):
                calls.append("guardrail_async")

        agent = Agent(name="test-agent", pre_hooks=[TestGuardrail().check])
        _patch_model(monkeypatch)

        result = agent_run._continue_run(
            agent,
            run_response=_make_paused_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            session=_make_session(),
            tools=[],
            user_id="user-1",
        )

        assert result.status == RunStatus.completed
        assert calls == ["guardrail"], "guardrails should always run on continue_run"

    def test_guardrail_blocks_continue_run(self, monkeypatch):
        """Guardrails that raise InputCheckError block continue_run."""
        model_called = []

        class BlockingGuardrail(BaseGuardrail):
            def check(self, run_input=None):
                raise InputCheckError("authorization denied")

            async def async_check(self, run_input=None):
                raise InputCheckError("authorization denied")

        def fake_model(*args, **kwargs):
            model_called.append(1)
            return ModelResponse(role="assistant", content="response")

        monkeypatch.setattr(agent_run, "call_model_with_fallback", fake_model)
        monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
        monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)

        agent = Agent(name="test-agent", pre_hooks=[BlockingGuardrail().check])

        result = agent_run._continue_run(
            agent,
            run_response=_make_paused_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            session=_make_session(),
            tools=[],
            user_id="user-1",
        )

        assert result.status == RunStatus.error
        assert "authorization denied" in str(result.content)
        assert model_called == [], "model should not be called when guardrail blocks"

    def test_combined_decorator_options(self, monkeypatch):
        """@hook with both run_in_background and run_on_continue works."""
        calls = []

        @hook(run_in_background=True, run_on_continue=True)
        def background_audit(run_input=None):
            calls.append("background_audit")

        # Verify the hook has both attributes set
        from agno.hooks.decorator import should_run_in_background, should_run_on_continue

        assert should_run_in_background(background_audit) is True
        assert should_run_on_continue(background_audit) is True


class TestHookDecoratorAttributes:
    """Tests for hook decorator attribute handling."""

    def test_should_run_on_continue_default_false(self):
        """Hooks without decorator return False for should_run_on_continue."""
        from agno.hooks.decorator import should_run_on_continue

        def plain_hook():
            pass

        assert should_run_on_continue(plain_hook) is False

    def test_should_run_on_continue_with_decorator(self):
        """Hooks with @hook(run_on_continue=True) return True."""
        from agno.hooks.decorator import should_run_on_continue

        @hook(run_on_continue=True)
        def continue_hook():
            pass

        assert should_run_on_continue(continue_hook) is True

    def test_decorator_without_run_on_continue(self):
        """@hook() without run_on_continue still returns False."""
        from agno.hooks.decorator import should_run_on_continue

        @hook()
        def basic_hook():
            pass

        assert should_run_on_continue(basic_hook) is False

    def test_bare_decorator(self):
        """@hook without parentheses returns False for run_on_continue."""
        from agno.hooks.decorator import should_run_on_continue

        @hook
        def bare_hook():
            pass

        assert should_run_on_continue(bare_hook) is False

    def test_async_hook_with_run_on_continue(self):
        """Async hooks work with @hook(run_on_continue=True)."""
        from agno.hooks.decorator import should_run_on_continue

        @hook(run_on_continue=True)
        async def async_hook():
            pass

        assert should_run_on_continue(async_hook) is True
