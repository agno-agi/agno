"""Unit tests for rolling session compaction + tool-message inclusion (#8790).

Two focused additions to SessionSummaryManager:
1. compact(summaryₙ, messages_to_fold) → summaryₙ₊₁ — incremental compaction
   that folds messages into an EXISTING summary instead of full re-summarization.
2. include_tool_messages — surface tool-role messages in the summary input
   (previously only user/assistant were included).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.run.agent import Message
from agno.session.summary import SessionSummary, SessionSummaryManager, SessionSummaryResponse


@pytest.fixture(autouse=True)
def _passthrough_get_model():
    """compact/acompact call get_model(model); pass the manager's mock model through unchanged."""
    with patch("agno.session.summary.get_model", side_effect=lambda m: m):
        yield


def _make_mock_model(parsed_summary: SessionSummaryResponse) -> MagicMock:
    """A mock Model whose response/aresponse return a parsed summary."""
    mock_model = MagicMock()
    mock_resp = MagicMock()
    mock_resp.parsed = parsed_summary
    mock_resp.content = parsed_summary.model_dump_json()
    mock_model.supports_native_structured_outputs = True
    mock_model.response.return_value = mock_resp
    mock_model.aresponse = AsyncMock(return_value=mock_resp)
    return mock_model


def _manager_with_mock_model(parsed_summary: SessionSummaryResponse) -> SessionSummaryManager:
    """Build a manager whose model.response/aresponse return a parsed summary.

    get_model (called inside compact/acompact) is patched at the module level so
    the MagicMock is returned as-is instead of being rejected as a non-Model.
    """
    return SessionSummaryManager(model=_make_mock_model(parsed_summary))


# --- compact(): incremental folding ---


def test_compact_folds_messages_into_existing_summary():
    """summaryₙ + fold batch → summaryₙ₊₁ (one model call, input bounded)."""
    existing = SessionSummary(summary="John is building an AI agent with Agno.")
    fold = [
        Message(role="user", content="Switch the DB to Postgres."),
        Message(role="assistant", content="Done — migrated to Postgres."),
    ]
    expected = SessionSummaryResponse(
        summary="John is building an AI agent with Agno using Postgres.", topics=["agno", "postgres"]
    )
    mgr = _manager_with_mock_model(expected)

    result = mgr.compact(existing, fold)

    assert result is not None
    assert "Postgres" in result.summary
    # Exactly one model call, and the existing summary was sent in the prompt.
    mgr.model.response.assert_called_once()
    sent_messages = mgr.model.response.call_args.kwargs["messages"]
    prompt_text = sent_messages[0].content
    assert "John is building an AI agent with Agno." in prompt_text  # existing summary seeded
    assert "Switch the DB to Postgres." in prompt_text  # folded messages included


@pytest.mark.asyncio
async def test_acompact_folds_messages_into_existing_summary():
    existing = SessionSummary(summary="Prior context: user likes Python.")
    fold = [Message(role="user", content="Also teach me Rust.")]
    expected = SessionSummaryResponse(summary="User likes Python and wants to learn Rust.")
    mgr = _manager_with_mock_model(expected)

    result = await mgr.acompact(existing, fold)

    assert result is not None
    assert "Rust" in result.summary
    mgr.model.aresponse.assert_awaited_once()


def test_compact_without_existing_summary_seeds_from_fold():
    """When there is no prior summary, compact bootstraps one from the fold batch."""
    fold = [Message(role="user", content="I'm Alice from Berlin.")]
    expected = SessionSummaryResponse(summary="Alice is from Berlin.")
    mgr = _manager_with_mock_model(expected)

    result = mgr.compact(None, fold)

    assert result is not None
    assert "Alice" in result.summary


def test_compact_no_model_returns_none():
    mgr = SessionSummaryManager(model=None)
    assert mgr.compact(SessionSummary(summary="x"), [Message(role="user", content="hi")]) is None


def test_compact_empty_fold_returns_none():
    """Nothing to fold → no model call, no new summary."""
    mgr = _manager_with_mock_model(SessionSummaryResponse(summary="anything"))
    assert mgr.compact(SessionSummary(summary="x"), []) is None
    mgr.model.response.assert_not_called()


def test_compact_updates_manager_summary_attribute():
    existing = SessionSummary(summary="old")
    expected = SessionSummaryResponse(summary="new integrated summary")
    mgr = _manager_with_mock_model(expected)

    mgr.compact(existing, [Message(role="user", content="more info")])

    assert mgr.summary is not None
    assert mgr.summary.summary == "new integrated summary"
    assert mgr.summaries_updated is True


# --- include_tool_messages ---


def test_default_excludes_tool_messages():
    """By default, tool messages are not rendered into the summary input."""
    mgr = SessionSummaryManager(model=MagicMock())
    mgr.model.supports_native_structured_outputs = True
    conversation = [
        Message(role="user", content="search the web"),
        Message(role="assistant", content="calling search tool"),
        Message(role="tool", content="result: agno is an agent SDK"),
    ]
    msg = mgr.get_system_message(conversation, response_format={"type": "json_object"})
    assert "search the web" in msg.content
    # Tool result is excluded by default.
    assert "result: agno is an agent SDK" not in msg.content


def test_include_tool_messages_renders_tool_results():
    """include_tool_messages=True surfaces tool-role messages in the summary input."""
    mgr = SessionSummaryManager(model=MagicMock(), include_tool_messages=True)
    mgr.model.supports_native_structured_outputs = True
    conversation = [
        Message(role="user", content="search the web"),
        Message(role="assistant", content="calling search tool"),
        Message(role="tool", content="result: agno is an agent SDK"),
    ]
    msg = mgr.get_system_message(conversation, response_format={"type": "json_object"})
    assert "result: agno is an agent SDK" in msg.content


def test_include_tool_messages_validation_rejects_negative():
    with pytest.raises(TypeError):
        SessionSummaryManager(model=MagicMock(), include_tool_messages="yes")  # type: ignore[arg-type]
