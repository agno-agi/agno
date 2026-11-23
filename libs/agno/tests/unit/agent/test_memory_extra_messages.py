"""Test that memory pipeline processes extra_messages when user_message is None.

When input_content is a List[Message], Agno sets extra_messages instead of
user_message. The memory pipeline should still run in this case.
"""

from concurrent.futures import Future
from unittest.mock import MagicMock

from agno.agent._managers import start_memory_future
from agno.models.message import Message
from agno.run.messages import RunMessages


def _make_agent(*, update_memory: bool = True, agentic: bool = False) -> MagicMock:
    agent = MagicMock()
    agent.memory_manager = MagicMock()
    agent.update_memory_on_run = update_memory
    agent.enable_agentic_memory = agentic
    agent.background_executor.submit.return_value = MagicMock(spec=Future)
    return agent


class TestStartMemoryFuture:
    def test_starts_when_user_message_present(self) -> None:
        agent = _make_agent()
        run_messages = RunMessages()
        run_messages.user_message = Message(role="user", content="Hello")

        result = start_memory_future(agent, run_messages, user_id="user-1")

        assert result is not None
        agent.background_executor.submit.assert_called_once()

    def test_starts_when_only_extra_messages_present(self) -> None:
        """Regression: extra_messages alone should trigger memory creation."""
        agent = _make_agent()
        run_messages = RunMessages()
        run_messages.user_message = None
        run_messages.extra_messages = [Message(role="user", content="Hello from list")]

        result = start_memory_future(agent, run_messages, user_id="user-1")

        assert result is not None
        agent.background_executor.submit.assert_called_once()

    def test_skips_when_no_messages_at_all(self) -> None:
        agent = _make_agent()
        run_messages = RunMessages()
        run_messages.user_message = None
        run_messages.extra_messages = None

        result = start_memory_future(agent, run_messages, user_id="user-1")

        assert result is None
        agent.background_executor.submit.assert_not_called()

    def test_skips_when_empty_extra_messages(self) -> None:
        agent = _make_agent()
        run_messages = RunMessages()
        run_messages.user_message = None
        run_messages.extra_messages = []

        result = start_memory_future(agent, run_messages, user_id="user-1")

        assert result is None
        agent.background_executor.submit.assert_not_called()

    def test_skips_when_memory_manager_is_none(self) -> None:
        agent = _make_agent()
        agent.memory_manager = None
        run_messages = RunMessages()
        run_messages.extra_messages = [Message(role="user", content="Hello")]

        result = start_memory_future(agent, run_messages, user_id="user-1")

        assert result is None

    def test_skips_when_update_memory_disabled(self) -> None:
        agent = _make_agent(update_memory=False)
        run_messages = RunMessages()
        run_messages.extra_messages = [Message(role="user", content="Hello")]

        result = start_memory_future(agent, run_messages, user_id="user-1")

        assert result is None
