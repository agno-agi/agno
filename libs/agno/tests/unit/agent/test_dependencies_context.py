"""Unit tests for add_dependencies_to_context with List[Message] input.

Tests that dependencies are properly injected into the last user message
when input is provided as List[Message], List[Dict], or string.
"""

import json

import pytest

from agno.agent.agent import Agent
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session.agent import AgentSession


@pytest.fixture
def agent():
    """Create a minimal agent for testing _get_run_messages."""
    a = Agent(build_context=False)
    a.set_id()
    return a


@pytest.fixture
def run_context_with_deps():
    """RunContext with dependencies set."""
    return RunContext(
        run_id="test-run",
        session_id="test-session",
        dependencies={"user_name": "Alice", "user_role": "admin"},
    )


@pytest.fixture
def run_context_no_deps():
    """RunContext without dependencies."""
    return RunContext(
        run_id="test-run",
        session_id="test-session",
        dependencies=None,
    )


@pytest.fixture
def run_context_empty_deps():
    """RunContext with empty dependencies dict."""
    return RunContext(
        run_id="test-run",
        session_id="test-session",
        dependencies={},
    )


@pytest.fixture
def run_output():
    return RunOutput()


@pytest.fixture
def session():
    return AgentSession(session_id="test-session")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_last_user_message(result) -> Message:
    """Return the last user-role message from result.messages."""
    for m in reversed(result.messages):
        if m.role == "user":
            return m
    raise AssertionError("No user message found in result.messages")


# ---------------------------------------------------------------------------
# Test: Dependencies injected with List[Message] input
# ---------------------------------------------------------------------------


class TestDependenciesWithListMessageInput:
    def test_dependencies_injected_into_last_user_message(
        self, agent, run_context_with_deps, run_output, session
    ):
        """Dependencies should be appended to the last user message content."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
            Message(role="user", content="What is my name?"),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        last_user = _get_last_user_message(result)
        assert last_user.content.startswith("What is my name?")
        assert "<additional context>" in last_user.content
        assert "Alice" in last_user.content
        assert "admin" in last_user.content

    def test_other_messages_not_modified(
        self, agent, run_context_with_deps, run_output, session
    ):
        """Non-last-user messages should not be modified while last user message is."""
        messages = [
            Message(role="user", content="First question"),
            Message(role="assistant", content="First answer"),
            Message(role="user", content="Second question"),
        ]

        agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        # Verify injection actually happened on the last user message
        assert "<additional context>" in messages[2].content
        # First user message should not be modified
        assert messages[0].content == "First question"
        # Assistant message should not be modified
        assert messages[1].content == "First answer"

    def test_dependencies_with_single_user_message_in_list(
        self, agent, run_context_with_deps, run_output, session
    ):
        """Dependencies work when there is only one user message."""
        messages = [
            Message(role="user", content="Hello"),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        user_msg = _get_last_user_message(result)
        assert user_msg.content.startswith("Hello")
        assert "<additional context>" in user_msg.content
        assert "Alice" in user_msg.content

    def test_dependencies_with_multimodal_content(
        self, agent, run_context_with_deps, run_output, session
    ):
        """Dependencies injected into multimodal message with type/text parts."""
        messages = [
            Message(
                role="user",
                content=[
                    {"type": "text", "text": "Describe this image"},
                    {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}},
                ],
            ),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        user_msg = _get_last_user_message(result)
        text_parts = [p for p in user_msg.content if isinstance(p, dict) and p.get("type") == "text"]
        assert len(text_parts) == 1
        assert text_parts[0]["text"].startswith("Describe this image")
        assert "<additional context>" in text_parts[0]["text"]
        assert "Alice" in text_parts[0]["text"]

    def test_no_crash_when_no_user_messages_in_list(
        self, agent, run_context_with_deps, run_output, session
    ):
        """No crash when List[Message] contains no user-role messages."""
        messages = [
            Message(role="assistant", content="I am ready"),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        # Should not crash; assistant message should be unmodified
        assert result.messages[0].content == "I am ready"


# ---------------------------------------------------------------------------
# Test: Dependencies injected with List[Dict] input (AGUI path)
# ---------------------------------------------------------------------------


class TestDependenciesWithListDictInput:
    def test_dependencies_injected_with_dict_messages(
        self, agent, run_context_with_deps, run_output, session
    ):
        """Dependencies should work when input is List[Dict] with role keys."""
        messages = [
            {"role": "user", "content": "Hello from AGUI"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "What is my role?"},
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        last_user = _get_last_user_message(result)
        assert last_user.content.startswith("What is my role?")
        assert "<additional context>" in last_user.content
        assert "admin" in last_user.content

    def test_dict_input_no_injection_when_disabled(
        self, agent, run_context_with_deps, run_output, session
    ):
        """No injection on List[Dict] input when disabled."""
        messages = [
            {"role": "user", "content": "Hello from AGUI"},
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=False,
        )

        last_user = _get_last_user_message(result)
        assert last_user.content == "Hello from AGUI"
        assert "<additional context>" not in last_user.content


# ---------------------------------------------------------------------------
# Test: No injection when add_dependencies_to_context=False
# ---------------------------------------------------------------------------


class TestNoDependenciesWhenDisabled:
    def test_no_injection_when_disabled_list_message(
        self, agent, run_context_with_deps, run_output, session
    ):
        """Dependencies should not be injected when add_dependencies_to_context=False."""
        messages = [
            Message(role="user", content="Hello"),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=False,
        )

        user_msg = _get_last_user_message(result)
        assert user_msg.content == "Hello"
        assert "<additional context>" not in user_msg.content

    def test_no_injection_when_default_none(
        self, agent, run_context_with_deps, run_output, session
    ):
        """No injection when add_dependencies_to_context is None (default)."""
        messages = [
            Message(role="user", content="Hello"),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=None,
        )

        user_msg = _get_last_user_message(result)
        assert user_msg.content == "Hello"
        assert "<additional context>" not in user_msg.content


# ---------------------------------------------------------------------------
# Test: No injection when dependencies is None or empty
# ---------------------------------------------------------------------------


class TestNoDependenciesWhenNoneOrEmpty:
    def test_no_injection_when_dependencies_none(
        self, agent, run_context_no_deps, run_output, session
    ):
        """No injection when run_context.dependencies is None."""
        messages = [
            Message(role="user", content="Hello"),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_no_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        user_msg = _get_last_user_message(result)
        assert user_msg.content == "Hello"
        assert "<additional context>" not in user_msg.content

    def test_no_injection_when_dependencies_empty_dict(
        self, agent, run_context_empty_deps, run_output, session
    ):
        """No injection when run_context.dependencies is {}."""
        messages = [
            Message(role="user", content="Hello"),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_empty_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        user_msg = _get_last_user_message(result)
        assert user_msg.content == "Hello"
        assert "<additional context>" not in user_msg.content


# ---------------------------------------------------------------------------
# Test: Dependencies with string input (existing behavior, regression check)
# ---------------------------------------------------------------------------


class TestDependenciesWithStringInput:
    def test_dependencies_injected_with_string_input(
        self, agent, run_context_with_deps, run_output, session
    ):
        """Dependencies should work with plain string input too (existing path)."""
        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input="What is my name?",
            session=session,
            add_dependencies_to_context=True,
        )

        assert result.user_message is not None
        assert result.user_message.content.startswith("What is my name?")
        assert "<additional context>" in result.user_message.content
        assert "Alice" in result.user_message.content

    def test_no_injection_string_input_when_disabled(
        self, agent, run_context_with_deps, run_output, session
    ):
        """No injection on string input when disabled."""
        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input="What is my name?",
            session=session,
            add_dependencies_to_context=False,
        )

        assert result.user_message is not None
        assert result.user_message.content == "What is my name?"
        assert "<additional context>" not in result.user_message.content


# ---------------------------------------------------------------------------
# Test: Dependencies content format
# ---------------------------------------------------------------------------


class TestDependenciesContentFormat:
    def test_dependencies_serialized_as_json(
        self, agent, run_context_with_deps, run_output, session
    ):
        """Dependencies should be serialized as JSON inside <additional context> tags."""
        messages = [
            Message(role="user", content="Hello"),
        ]

        result = agent._get_run_messages(
            run_response=run_output,
            run_context=run_context_with_deps,
            input=messages,
            session=session,
            add_dependencies_to_context=True,
        )

        user_msg = _get_last_user_message(result)
        content = user_msg.content
        # Verify the tags are present
        assert "<additional context>" in content
        assert "</additional context>" in content
        # Extract and parse the JSON between tags
        start = content.index("<additional context>\n") + len("<additional context>\n")
        end = content.index("\n</additional context>")
        parsed = json.loads(content[start:end])
        assert parsed == {"user_name": "Alice", "user_role": "admin"}
