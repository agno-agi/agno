"""Derived views: no-overlap, elision on copies, chaining strip, fail-open on anchor miss."""

from agno.compaction._notice import NOTICE_OPEN_TAG
from agno.compaction._view import build_view
from agno.compaction.compaction import CompactionRecord
from agno.compaction.prompts import ELISION_PLACEHOLDER, SUMMARY_PREFIX
from agno.models.message import Message


def user(text="hello", **kwargs):
    return Message(role="user", content=text, **kwargs)


def tool_result(call_id, content, name="lookup"):
    return Message(role="tool", tool_call_id=call_id, tool_name=name, content=content)


def make_log():
    return [
        Message(role="system", content="sys"),
        user("turn 1"),
        Message(role="assistant", content="reply 1"),
        user("turn 2"),
        Message(role="assistant", content="reply 2"),
        user("turn 3"),
        Message(role="assistant", content="reply 3"),
    ]


def record_with_boundary(messages, boundary_index, summary="the summary", notice=None):
    record = CompactionRecord.create("threshold")
    record.summary = summary
    record.first_kept_message_id = messages[boundary_index].id
    record.notice = notice
    return record


class TestNoRecord:
    def test_pass_through(self):
        messages = make_log()
        view = build_view(messages, None)
        assert view == messages
        assert view is not messages  # a new list, same members

    def test_chaining_strip_without_record(self):
        messages = make_log()
        messages[2].provider_data = {"response_id": "resp_1"}
        view = build_view(messages, None, strip_provider_chaining=True)
        stripped = view[2]
        assert stripped.provider_data is None
        assert messages[2].provider_data == {"response_id": "resp_1"}  # canonical untouched
        assert stripped.id == messages[2].id


class TestRecordApplied:
    def test_cut_and_injection(self):
        messages = make_log()
        record = record_with_boundary(messages, 5, notice=NOTICE_OPEN_TAG + "\nstate\n</context_survived>")
        view = build_view(messages, record)
        assert view[0].role == "system"
        assert view[1].content.startswith(SUMMARY_PREFIX)
        assert "the summary" in view[1].content
        assert view[2].content.startswith(NOTICE_OPEN_TAG)
        assert [m.id for m in view[3:]] == [m.id for m in messages[5:]]
        # No pre-boundary content anywhere in the view.
        view_ids = {m.id for m in view}
        for pre in messages[1:5]:
            assert pre.id not in view_ids

    def test_no_notice_message_when_record_has_none(self):
        messages = make_log()
        record = record_with_boundary(messages, 5, notice=None)
        view = build_view(messages, record)
        assert view[1].content.startswith(SUMMARY_PREFIX)
        assert view[2].id == messages[5].id

    def test_unresolvable_boundary_injects_nothing(self):
        messages = make_log()
        record = record_with_boundary(messages, 5)
        record.first_kept_message_id = "msg-gone"
        view = build_view(messages, record)
        assert all(not (isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX)) for m in view)
        assert [m.id for m in view] == [m.id for m in messages]

    def test_previous_injected_pair_dropped_on_reinjection(self):
        messages = make_log()
        old_pair = Message(role="user", content=SUMMARY_PREFIX + "old", from_history=True)
        messages.insert(1, old_pair)
        record = record_with_boundary(messages, 6, summary="new summary")
        view = build_view(messages, record)
        summaries = [m for m in view if isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX)]
        assert len(summaries) == 1
        assert "new summary" in summaries[0].content

    def test_summary_message_tagged_from_history(self):
        messages = make_log()
        view = build_view(messages, record_with_boundary(messages, 5))
        assert view[1].from_history is True


class TestElision:
    def make_tool_log(self):
        return [
            Message(role="system", content="sys"),
            Message(role="assistant", content=None, tool_calls=[{"id": "c1", "function": {"name": "lookup"}}]),
            tool_result("c1", "big old result " * 50),
            Message(role="assistant", content=None, tool_calls=[{"id": "c2", "function": {"name": "fetch"}}]),
            tool_result("c2", "recent result", name="fetch"),
            Message(role="assistant", content="done"),
        ]

    def watermark_record(self, messages, watermark_index):
        record = CompactionRecord.create("threshold")
        record.elision_watermark_message_id = messages[watermark_index].id
        return record

    def test_old_tool_results_elided_on_copies(self):
        messages = self.make_tool_log()
        original_content = messages[2].content
        view = build_view(messages, self.watermark_record(messages, 3))
        elided = next(m for m in view if m.id == messages[2].id)
        assert elided.content == ELISION_PLACEHOLDER.format(n_chars=len(original_content))
        assert messages[2].content == original_content  # canonical untouched
        kept = next(m for m in view if m.id == messages[4].id)
        assert kept.content == "recent result"

    def test_envelopes_never_elided(self):
        messages = self.make_tool_log()
        messages[2] = Message(
            role="tool",
            tool_call_id="c1",
            tool_name="lookup",
            content='<result id="res_ab" tool="lookup" lines="9" size="1 KB">\npreview\n</result>',
            id=messages[2].id,
        )
        view = build_view(messages, self.watermark_record(messages, 3))
        envelope = next(m for m in view if m.id == messages[2].id)
        assert "res_ab" in envelope.content

    def test_excluded_tools_never_elided(self):
        messages = self.make_tool_log()
        view = build_view(messages, self.watermark_record(messages, 3), elide_exclude_tools=["lookup"])
        kept = next(m for m in view if m.id == messages[2].id)
        assert kept.content == messages[2].content

    def test_unresolvable_watermark_degrades_to_no_elision(self):
        messages = self.make_tool_log()
        record = CompactionRecord.create("threshold")
        record.elision_watermark_message_id = "msg-gone"
        view = build_view(messages, record)
        assert [m.content for m in view] == [m.content for m in messages]
