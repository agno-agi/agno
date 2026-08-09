from unittest.mock import MagicMock

from agno.compression.context import (
    SUMMARY_PREFIX,
    CompactionState,
    ContextCompactionManager,
)
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput


def _make_messages(count: int, start_id: int = 1) -> list[Message]:
    messages = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(Message(id=f"msg-{start_id + i}", role=role, content=f"Message {start_id + i}"))
    return messages


def _make_mock_model(token_count: int = 1000, summary_response: str = "Summary of conversation") -> MagicMock:
    mock = MagicMock()
    mock.count_tokens = MagicMock(return_value=token_count)
    mock.response = MagicMock(return_value=ModelResponse(content=summary_response))
    mock.aresponse = MagicMock(return_value=ModelResponse(content=summary_response))
    return mock


def _make_manager_with_mock(
    mock_model: MagicMock,
    message_limit: int | None = None,
    token_limit: int | None = None,
    keep_recent: int = 10,
    preserve_user_budget: int | None = None,
) -> ContextCompactionManager:
    # Create manager without model to avoid get_model() validation
    manager = ContextCompactionManager(
        message_limit=message_limit,
        token_limit=token_limit,
        keep_recent=keep_recent,
        preserve_user_budget=preserve_user_budget,
    )
    # Assign mock directly after initialization
    manager.model = mock_model
    return manager


# === Initialization Tests ===


def test_default_message_limit_when_no_limits_specified():
    manager = ContextCompactionManager()
    assert manager.message_limit == 50
    assert manager.token_limit is None


def test_message_limit_preserved_when_specified():
    manager = ContextCompactionManager(message_limit=100)
    assert manager.message_limit == 100
    assert manager.token_limit is None


def test_token_limit_preserved_when_specified():
    manager = ContextCompactionManager(token_limit=50000)
    assert manager.token_limit == 50000
    assert manager.message_limit is None


def test_both_limits_preserved_when_specified():
    manager = ContextCompactionManager(message_limit=30, token_limit=40000)
    assert manager.message_limit == 30
    assert manager.token_limit == 40000


def test_preserve_user_budget_derived_from_token_limit():
    manager = ContextCompactionManager(token_limit=100000)
    assert manager.preserve_user_budget == 25000  # 25% of 100000


def test_preserve_user_budget_default_fallback():
    manager = ContextCompactionManager(message_limit=50)
    assert manager.preserve_user_budget == 20000  # default when no token_limit


def test_preserve_user_budget_explicit_override():
    manager = ContextCompactionManager(token_limit=100000, preserve_user_budget=5000)
    assert manager.preserve_user_budget == 5000  # explicit override


# === should_compact Tests ===


def test_should_compact_below_message_limit():
    manager = ContextCompactionManager(message_limit=50)
    messages = _make_messages(30)
    assert manager.should_compact(messages) is False


def test_should_compact_at_message_limit():
    manager = ContextCompactionManager(message_limit=50)
    messages = _make_messages(50)
    assert manager.should_compact(messages) is True


def test_should_compact_above_message_limit():
    manager = ContextCompactionManager(message_limit=50)
    messages = _make_messages(60)
    assert manager.should_compact(messages) is True


def test_should_compact_below_token_limit():
    mock_model = _make_mock_model(token_count=40000)
    manager = _make_manager_with_mock(mock_model, token_limit=50000)
    messages = _make_messages(10)
    assert manager.should_compact(messages) is False
    mock_model.count_tokens.assert_called_once_with(messages)


def test_should_compact_at_token_limit():
    mock_model = _make_mock_model(token_count=50000)
    manager = _make_manager_with_mock(mock_model, token_limit=50000)
    messages = _make_messages(10)
    assert manager.should_compact(messages) is True


def test_should_compact_above_token_limit():
    mock_model = _make_mock_model(token_count=60000)
    manager = _make_manager_with_mock(mock_model, token_limit=50000)
    messages = _make_messages(10)
    assert manager.should_compact(messages) is True


def test_should_compact_token_limit_without_model():
    manager = ContextCompactionManager(token_limit=50000, model=None)
    messages = _make_messages(10)
    # No model to count tokens, but message count is below default 50
    assert manager.should_compact(messages) is False


def test_should_compact_token_limit_triggers_before_message_limit():
    mock_model = _make_mock_model(token_count=60000)
    manager = _make_manager_with_mock(mock_model, token_limit=50000, message_limit=100)
    messages = _make_messages(30)  # Below message limit of 100
    assert manager.should_compact(messages) is True  # Token limit triggers


# === compact Tests - No Compaction Cases ===


def test_compact_returns_original_when_no_model():
    manager = ContextCompactionManager(message_limit=10, model=None)
    messages = _make_messages(20)
    result = manager.compact(messages)
    assert result.compacted_messages == messages
    assert result.summary is None


def test_compact_returns_original_when_below_threshold():
    mock_model = _make_mock_model()
    manager = _make_manager_with_mock(mock_model, message_limit=50)
    messages = _make_messages(20)
    result = manager.compact(messages)
    assert result.compacted_messages == messages
    assert result.summary is None


def test_compact_returns_original_when_empty_messages():
    mock_model = _make_mock_model()
    manager = _make_manager_with_mock(mock_model, message_limit=10)
    result = manager.compact([])
    assert result.compacted_messages == []
    assert result.summary is None


# === compact Tests - Compaction Occurs ===


def test_compact_generates_summary():
    mock_model = _make_mock_model(token_count=60000, summary_response="Compressed summary")
    manager = _make_manager_with_mock(mock_model, token_limit=50000, keep_recent=5)
    messages = _make_messages(20)

    result = manager.compact(messages)

    assert result.summary == "Compressed summary"
    assert len(result.compacted_messages) < len(messages)
    mock_model.response.assert_called_once()


def test_compact_keeps_system_messages():
    mock_model = _make_mock_model(token_count=60000, summary_response="Summary")
    manager = _make_manager_with_mock(mock_model, token_limit=50000, keep_recent=3)

    messages = [
        Message(id="sys-1", role="system", content="System prompt"),
        *_make_messages(20),
    ]

    result = manager.compact(messages)

    system_msgs = [m for m in result.compacted_messages if m.role == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0].content == "System prompt"


def test_compact_keeps_recent_messages():
    mock_model = _make_mock_model(token_count=60000, summary_response="Summary")
    manager = _make_manager_with_mock(mock_model, token_limit=50000, keep_recent=5)

    messages = _make_messages(20)
    original_recent_ids = {m.id for m in messages[-5:]}

    result = manager.compact(messages)

    result_ids = {m.id for m in result.compacted_messages if m.id and not m.from_history}
    assert original_recent_ids.issubset(result_ids)


def test_compact_injects_summary_message():
    mock_model = _make_mock_model(token_count=60000, summary_response="The summary")
    manager = _make_manager_with_mock(mock_model, token_limit=50000, keep_recent=5)

    messages = _make_messages(20)
    result = manager.compact(messages)

    summary_msgs = [m for m in result.compacted_messages if m.from_history]
    assert len(summary_msgs) == 1
    assert summary_msgs[0].content.startswith(SUMMARY_PREFIX)
    assert "The summary" in summary_msgs[0].content


def test_compact_updates_run_response_state():
    mock_model = _make_mock_model(token_count=60000, summary_response="Summary")
    manager = _make_manager_with_mock(mock_model, token_limit=50000, keep_recent=5)

    messages = _make_messages(20)
    run_response = RunOutput(run_id="test-run", agent_id="test-agent", session_id="test-session")

    manager.compact(messages, run_response=run_response)

    assert run_response.compaction_state is not None
    assert run_response.compaction_state.summary == "Summary"
    assert run_response.compaction_state.total_compactions == 1


def test_compact_accumulates_compacted_message_ids():
    mock_model = _make_mock_model(token_count=60000, summary_response="Summary")
    manager = _make_manager_with_mock(mock_model, token_limit=50000, keep_recent=5)

    messages = _make_messages(20)
    run_response = RunOutput(run_id="test-run", agent_id="test-agent", session_id="test-session")

    manager.compact(messages, run_response=run_response)

    assert len(run_response.compaction_state.compacted_message_ids) > 0
    # IDs should be from the old messages that were summarized
    for msg_id in run_response.compaction_state.compacted_message_ids:
        assert msg_id.startswith("msg-")


def test_compact_increments_total_compactions():
    mock_model = _make_mock_model(token_count=60000, summary_response="Summary")
    manager = _make_manager_with_mock(mock_model, token_limit=50000, keep_recent=5)

    messages = _make_messages(20)

    # First compaction
    existing_state = CompactionState(total_compactions=2)
    run_response = RunOutput(
        run_id="test-run",
        agent_id="test-agent",
        session_id="test-session",
        compaction_state=existing_state,
    )

    manager.compact(messages, run_response=run_response)

    assert run_response.compaction_state.total_compactions == 3


# === compact Tests - Error Handling ===


def test_compact_returns_original_on_llm_failure():
    mock_model = _make_mock_model(token_count=60000)
    mock_model.response = MagicMock(side_effect=Exception("LLM Error"))
    manager = _make_manager_with_mock(mock_model, token_limit=50000, keep_recent=5)

    messages = _make_messages(20)
    result = manager.compact(messages)

    assert result.compacted_messages == messages
    assert result.summary is None


# === _extract_user_messages Tests ===
# Returns (preserved_messages, preserved_indices)


def test_extract_user_messages_respects_budget():
    mock_model = _make_mock_model()
    # Each message counts as 100 tokens
    mock_model.count_tokens = MagicMock(return_value=100)
    manager = _make_manager_with_mock(mock_model, preserve_user_budget=250)

    messages = [
        Message(id="u1", role="user", content="User 1"),
        Message(id="a1", role="assistant", content="Assistant 1"),
        Message(id="u2", role="user", content="User 2"),
        Message(id="a2", role="assistant", content="Assistant 2"),
        Message(id="u3", role="user", content="User 3"),
    ]

    preserved, indices = manager._extract_user_messages(messages)

    # Budget 250 allows ~2 user messages (100 tokens each)
    assert len(preserved) <= 3
    # Should preserve from most recent
    preserved_ids = {m.id for m in preserved}
    assert "u3" in preserved_ids or "u2" in preserved_ids


def test_extract_user_messages_skips_summary_messages():
    mock_model = _make_mock_model()
    mock_model.count_tokens = MagicMock(return_value=50)
    manager = _make_manager_with_mock(mock_model, preserve_user_budget=10000)

    messages = [
        Message(id="sum", role="user", content="Previous summary", from_history=True),
        Message(id="u1", role="user", content="Real user message"),
    ]

    preserved, indices = manager._extract_user_messages(messages)

    preserved_ids = {m.id for m in preserved}
    assert "sum" not in preserved_ids
    assert "u1" in preserved_ids


# === Async Parity Tests ===


async def test_ashould_compact_message_limit():
    manager = ContextCompactionManager(message_limit=10)
    messages = _make_messages(15)

    result = await manager.ashould_compact(messages)

    assert result is True


async def test_ashould_compact_below_message_limit():
    manager = ContextCompactionManager(message_limit=50)
    messages = _make_messages(10)

    result = await manager.ashould_compact(messages)

    assert result is False


# === _split_messages Tests ===
# Returns (old_messages, preserved_user, recent_messages)


def test_split_messages_keeps_recent_intact():
    mock_model = _make_mock_model()
    manager = _make_manager_with_mock(mock_model, keep_recent=5)

    messages = _make_messages(15)

    old_msgs, preserved_user, recent_msgs = manager._split_messages(messages)

    assert len(recent_msgs) == 5
    # old_msgs + preserved_user should account for the rest
    assert len(old_msgs) + len(preserved_user) + len(recent_msgs) == 15
    # Recent should be the last 5
    expected_recent_ids = {m.id for m in messages[-5:]}
    actual_recent_ids = {m.id for m in recent_msgs}
    assert expected_recent_ids == actual_recent_ids


def test_split_messages_fewer_than_keep_recent():
    mock_model = _make_mock_model()
    manager = _make_manager_with_mock(mock_model, keep_recent=10)

    messages = _make_messages(5)

    old_msgs, preserved_user, recent_msgs = manager._split_messages(messages)

    # All messages are "recent" since count < keep_recent
    assert len(old_msgs) == 0
    assert len(preserved_user) == 0
    assert len(recent_msgs) == 5


def test_split_messages_extracts_preserved_user():
    mock_model = _make_mock_model()
    mock_model.count_tokens = MagicMock(return_value=50)  # Small tokens per message
    manager = _make_manager_with_mock(mock_model, keep_recent=2, preserve_user_budget=1000)

    messages = [
        Message(id="u1", role="user", content="User 1"),
        Message(id="a1", role="assistant", content="Asst 1"),
        Message(id="u2", role="user", content="User 2"),
        Message(id="a2", role="assistant", content="Asst 2"),
        Message(id="u3", role="user", content="User 3"),
        Message(id="a3", role="assistant", content="Asst 3"),
    ]

    old_msgs, preserved_user, recent_msgs = manager._split_messages(messages)

    # Recent = last 2 messages
    assert len(recent_msgs) == 2
    # preserved_user should have user messages from older portion
    preserved_roles = [m.role for m in preserved_user]
    assert all(r == "user" for r in preserved_roles)
