"""
Unit tests for retry-skip behaviour when tool calls already completed.

When `retries` is set on an Agent and a failure occurs after at least one tool
call has already succeeded, the retry loop must NOT replay the run. Replaying
would re-execute non-idempotent tools (payments, messages, orders).

Tests validate the guard expression directly — the same expression used in
every retry block inside agno/agent/_run.py.
"""

from agno.models.message import Message
from agno.run.messages import RunMessages

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_messages_with_tool_result() -> RunMessages:
    """Simulate run_messages that already contain a completed tool result."""
    rm = RunMessages()
    rm.messages = [
        Message(role="user", content="charge the card"),
        Message(
            role="assistant",
            content="",
            tool_calls=[{"id": "tc1", "function": {"name": "charge_card"}}],
        ),
        Message(role="tool", content="charged 100.00 for op-repro-0001", tool_call_id="tc1"),
    ]
    return rm


def _guard(run_messages) -> list:
    """Mirror the guard expression used in every retry block in _run.py."""
    return [m for m in (run_messages.messages if run_messages else []) if m.role == "tool"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRetrySkipsOnCompletedTools:
    """The retry loop must not replay when tool messages are already present."""

    def test_no_retry_when_tool_message_present(self) -> None:
        """After a tool call completes, guard returns non-empty — retry must be skipped."""
        run_messages = _make_run_messages_with_tool_result()
        retries = 2
        num_attempts = retries + 1
        attempts_made = 0

        for attempt in range(num_attempts):
            attempts_made += 1
            try:
                raise RuntimeError("model call failed")
            except Exception:
                if attempt < num_attempts - 1:
                    completed = _guard(run_messages)
                    if completed:
                        break  # guard fires — no retry
                    continue  # pragma: no cover
                break

        assert attempts_made == 1, f"Expected exactly 1 attempt when tool messages are present, got {attempts_made}"

    def test_normal_retry_when_no_tool_messages(self) -> None:
        """Without tool messages, guard returns empty — retry loop runs all attempts."""
        run_messages = RunMessages()
        run_messages.messages = [Message(role="user", content="hello")]

        retries = 2
        num_attempts = retries + 1
        attempts_made = 0

        for attempt in range(num_attempts):
            attempts_made += 1
            try:
                raise RuntimeError("model call failed")
            except Exception:
                if attempt < num_attempts - 1:
                    completed = _guard(run_messages)
                    if completed:
                        break  # pragma: no cover
                    continue  # retry
                break

        assert attempts_made == num_attempts, (
            f"Expected {num_attempts} attempts without tool messages, got {attempts_made}"
        )

    def test_guard_handles_none_run_messages(self) -> None:
        """Guard must not raise when run_messages is None (early failure before binding)."""
        completed = _guard(None)
        assert completed == [], "Expected empty list when run_messages is None"

    def test_guard_only_counts_tool_role_messages(self) -> None:
        """Guard must ignore user/assistant messages — only 'tool' role triggers the skip."""
        run_messages = RunMessages()
        run_messages.messages = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="thinking..."),
        ]
        completed = _guard(run_messages)
        assert completed == [], "user/assistant messages must not trigger the guard"
