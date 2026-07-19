"""Tests for ``flush_in_flight_messages_on_error``.

The helper rescues the in-flight conversation from ``run_messages.messages``
into ``run_response.messages`` when the model loop raises before any
checkpoint hook fires. Without this, the terminal ERROR write persists an
empty-message row and the conversation that led to the failure is lost.

Reviewer concern (Yash): "if a tool raises an error on the first batch, the
conversation isn't persisted on the run." This helper closes that gap for
the precise scenario where it's real: failures that escape the model loop
before any tool batch boundary fires.
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.agent._run import flush_in_flight_messages_on_error
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.messages import RunMessages


class TestFlushInFlightMessagesOnError:
    def test_flushes_when_run_response_messages_is_none(self):
        rr = RunOutput(run_id="r1")
        assert rr.messages is None
        rm = RunMessages()
        rm.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="hi"),
        ]
        flush_in_flight_messages_on_error(rr, rm)
        assert rr.messages is not None
        assert len(rr.messages) == 2
        assert rr.messages[1].content == "hi"

    def test_flushes_when_run_response_messages_is_empty_list(self):
        rr = RunOutput(run_id="r1", messages=[])
        rm = RunMessages()
        rm.messages = [Message(role="user", content="hi")]
        flush_in_flight_messages_on_error(rr, rm)
        assert rr.messages is not None
        assert len(rr.messages) == 1

    def test_does_not_overwrite_existing_messages(self):
        """If a mid-run checkpoint hook already populated run_response.messages,
        we must not stomp on it — that population may be more complete than
        the current run_messages snapshot."""
        existing = [Message(role="user", content="from-checkpoint")]
        rr = RunOutput(run_id="r1", messages=existing)
        rm = RunMessages()
        rm.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="from-rm"),
        ]
        flush_in_flight_messages_on_error(rr, rm)
        # Unchanged
        assert rr.messages is existing
        assert rr.messages[0].content == "from-checkpoint"

    def test_filters_messages_by_add_to_agent_memory(self):
        """Matches the filter the per-batch checkpoint hook uses, so the
        persisted shape is consistent regardless of which path flushed."""
        rr = RunOutput(run_id="r1")
        m_keep = Message(role="user", content="keep")
        m_drop = Message(role="user", content="drop", add_to_agent_memory=False)
        rm = RunMessages()
        rm.messages = [m_keep, m_drop]
        flush_in_flight_messages_on_error(rr, rm)
        assert rr.messages == [m_keep]

    def test_no_op_when_run_messages_is_none(self):
        """Some early failures happen before run_messages is even bound.
        The call sites pass locals().get('run_messages'), so we may get
        None — must not crash."""
        rr = RunOutput(run_id="r1")
        flush_in_flight_messages_on_error(rr, None)
        assert rr.messages is None

    def test_no_op_when_run_messages_has_no_messages(self):
        rr = RunOutput(run_id="r1")
        rm = RunMessages()
        rm.messages = []
        flush_in_flight_messages_on_error(rr, rm)
        assert rr.messages is None
