"""Tests for agent hook execution — metadata injection and guardrail background safety."""

from unittest.mock import MagicMock

import pytest

from agno.agent._hooks import _is_guardrail_hook, execute_post_hooks, execute_pre_hooks
from agno.exceptions import InputCheckError
from agno.guardrails.pii import PIIDetectionGuardrail
from agno.run import RunContext
from agno.run.agent import RunInput, RunOutput
from agno.session import AgentSession


def _make_agent(**overrides):
    agent = MagicMock()
    agent.debug_mode = False
    agent._run_hooks_in_background = False
    agent.events_to_skip = set()
    agent.store_events = False
    for k, v in overrides.items():
        setattr(agent, k, v)
    return agent


def _make_run_context(metadata=None):
    ctx = MagicMock(spec=RunContext)
    ctx.metadata = metadata
    return ctx


def _make_run_input(content="hello"):
    ri = MagicMock(spec=RunInput)
    ri.input_content = content
    ri.input_content_string.return_value = content
    return ri


def _make_run_output():
    return MagicMock(spec=RunOutput)


# --- P-H1: metadata in all_args ---


def test_pre_hook_receives_metadata():
    """Pre-hooks should receive metadata from run_context."""
    received = {}

    def my_hook(run_input, metadata):
        received["metadata"] = metadata

    agent = _make_agent()
    run_input = _make_run_input()
    run_context = _make_run_context(metadata={"email": "test@example.com"})
    session = MagicMock(spec=AgentSession)
    run_response = _make_run_output()
    run_response.input = run_input

    list(
        execute_pre_hooks(
            agent,
            hooks=[my_hook],
            run_response=run_response,
            run_input=run_input,
            session=session,
            run_context=run_context,
        )
    )

    assert received["metadata"] == {"email": "test@example.com"}


def test_post_hook_receives_metadata():
    """Post-hooks should receive metadata from run_context."""
    received = {}

    def my_hook(run_output, metadata):
        received["metadata"] = metadata

    agent = _make_agent()
    run_context = _make_run_context(metadata={"key": "value"})
    session = MagicMock(spec=AgentSession)
    run_output = _make_run_output()

    list(
        execute_post_hooks(
            agent,
            hooks=[my_hook],
            run_output=run_output,
            session=session,
            run_context=run_context,
        )
    )

    assert received["metadata"] == {"key": "value"}


def test_hook_metadata_none_when_no_run_context():
    """Metadata should be None when run_context is None."""
    received = {}

    def my_hook(run_input, metadata):
        received["metadata"] = metadata

    agent = _make_agent()
    run_input = _make_run_input()
    session = MagicMock(spec=AgentSession)
    run_response = _make_run_output()
    run_response.input = run_input

    list(
        execute_pre_hooks(
            agent,
            hooks=[my_hook],
            run_response=run_response,
            run_input=run_input,
            session=session,
            run_context=None,
        )
    )

    assert received["metadata"] is None


# --- P-H2: guardrail detection ---


def test_is_guardrail_hook_detects_bound_method():
    """_is_guardrail_hook should detect bound methods from BaseGuardrail instances."""
    guardrail = PIIDetectionGuardrail()
    assert _is_guardrail_hook(guardrail.check) is True
    assert _is_guardrail_hook(guardrail.async_check) is True


def test_is_guardrail_hook_rejects_plain_functions():
    """_is_guardrail_hook should return False for plain functions."""

    def plain_hook(run_input):
        pass

    assert _is_guardrail_hook(plain_hook) is False


def test_guardrail_not_backgrounded_when_run_hooks_in_background():
    """Guardrails should run inline even when _run_hooks_in_background=True."""
    guardrail = PIIDetectionGuardrail()

    agent = _make_agent(_run_hooks_in_background=True)
    run_input = _make_run_input("My SSN is 123-45-6789")
    run_context = _make_run_context()
    session = MagicMock(spec=AgentSession)
    run_response = _make_run_output()
    run_response.input = run_input
    background_tasks = MagicMock()

    with pytest.raises(InputCheckError):
        list(
            execute_pre_hooks(
                agent,
                hooks=[guardrail.check],
                run_response=run_response,
                run_input=run_input,
                session=session,
                run_context=run_context,
                background_tasks=background_tasks,
            )
        )

    # Guardrail should NOT have been added to background tasks
    background_tasks.add_task.assert_not_called()


def test_non_guardrail_hooks_still_backgrounded():
    """Regular hooks should still be backgrounded when _run_hooks_in_background=True."""

    def my_hook(run_input):
        pass

    agent = _make_agent(_run_hooks_in_background=True)
    run_input = _make_run_input()
    run_context = _make_run_context()
    session = MagicMock(spec=AgentSession)
    run_response = _make_run_output()
    run_response.input = run_input
    background_tasks = MagicMock()

    list(
        execute_pre_hooks(
            agent,
            hooks=[my_hook],
            run_response=run_response,
            run_input=run_input,
            session=session,
            run_context=run_context,
            background_tasks=background_tasks,
        )
    )

    background_tasks.add_task.assert_called_once()


# --- P-H4: email regex ---


def test_pii_email_regex_no_pipe():
    """Email regex should not match pipe character as valid TLD character."""
    guardrail = PIIDetectionGuardrail(
        enable_ssn_check=False,
        enable_credit_card_check=False,
        enable_phone_check=False,
    )
    pattern = guardrail.pii_patterns["Email"]
    assert pattern.search("user@example.com") is not None
    # Pipe should NOT be matched as a valid TLD character
    assert pattern.search("user@example.c|m") is None


# --- P-H3: PII mask type coercion ---


def test_pii_mask_preserves_string_type():
    """Masking should work for string input_content."""
    guardrail = PIIDetectionGuardrail(
        mask_pii=True,
        enable_ssn_check=True,
        enable_credit_card_check=False,
        enable_email_check=False,
        enable_phone_check=False,
    )
    run_input = RunInput(input_content="My SSN is 123-45-6789")
    guardrail.check(run_input)
    assert isinstance(run_input.input_content, str)
    assert "123-45-6789" not in run_input.input_content


def test_pii_mask_raises_for_non_string_input():
    """Masking should raise InputCheckError for non-string input to avoid type coercion."""
    guardrail = PIIDetectionGuardrail(
        mask_pii=True,
        enable_ssn_check=True,
        enable_credit_card_check=False,
        enable_email_check=False,
        enable_phone_check=False,
    )
    run_input = RunInput(input_content=["My SSN is 123-45-6789"])
    with pytest.raises(InputCheckError):
        guardrail.check(run_input)


# --- Codex-suggested edge cases ---


def test_kwargs_hook_receives_metadata():
    """Hooks with **kwargs should receive metadata without breaking."""
    received = {}

    def my_hook(run_input, **kwargs):
        received.update(kwargs)

    agent = _make_agent()
    run_input = _make_run_input()
    run_context = _make_run_context(metadata={"key": "val"})
    session = MagicMock(spec=AgentSession)
    run_response = _make_run_output()
    run_response.input = run_input

    list(
        execute_pre_hooks(
            agent,
            hooks=[my_hook],
            run_response=run_response,
            run_input=run_input,
            session=session,
            run_context=run_context,
        )
    )

    assert "metadata" in received
    assert received["metadata"] == {"key": "val"}


def test_partial_wrapped_guardrail_detected():
    """Guardrails wrapped in functools.partial should still be detected."""
    from functools import partial

    guardrail = PIIDetectionGuardrail()
    wrapped = partial(guardrail.check)
    assert _is_guardrail_hook(wrapped) is True
