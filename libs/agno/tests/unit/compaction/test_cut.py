"""Boundary and watermark selection: pair-safety, anchor durability, monotonicity."""

import pytest

from agno.compaction._cut import (
    choose_boundary,
    choose_watermark,
    is_injected_compaction_message,
    is_offload_envelope,
    keep_tail_start,
    leading_system_count,
)
from agno.compaction._notice import NOTICE_OPEN_TAG
from agno.compaction.prompts import SUMMARY_PREFIX
from agno.models.message import Message


def user(text="hello", **kwargs):
    return Message(role="user", content=text, **kwargs)


def assistant(text="ok", tool_calls=None, **kwargs):
    return Message(role="assistant", content=text, tool_calls=tool_calls, **kwargs)


def batch(call_id, result="result", name="lookup"):
    return [
        Message(role="assistant", content=None, tool_calls=[{"id": call_id, "function": {"name": name}}]),
        Message(role="tool", tool_call_id=call_id, tool_name=name, content=result),
    ]


def long_text(tokens):
    # The local estimator resolves ~4 chars or one token per word; words are robust either way.
    return "word " * tokens


@pytest.fixture
def exact_tokens(monkeypatch):
    """Deterministic estimator for boundary-precision tests: one token per 'word'."""
    import agno.compaction._cut as cut_module

    monkeypatch.setattr(
        cut_module,
        "estimate_message_tokens",
        lambda m: (m.content.count("word") if isinstance(m.content, str) else 0) or 1,
    )


class TestHelpers:
    def test_leading_system_count(self):
        messages = [Message(role="system", content="s"), user(), Message(role="system", content="late")]
        assert leading_system_count(messages) == 1

    def test_injected_pair_detection(self):
        summary = Message(role="user", content=SUMMARY_PREFIX + "stuff", from_history=True)
        notice = Message(role="user", content=NOTICE_OPEN_TAG + "\nstuff", from_history=True)
        organic = Message(role="user", content=SUMMARY_PREFIX + "stuff")  # not from_history
        assert is_injected_compaction_message(summary)
        assert is_injected_compaction_message(notice)
        assert not is_injected_compaction_message(organic)
        assert not is_injected_compaction_message(user())

    def test_envelope_detection(self):
        envelope = Message(
            role="tool", tool_call_id="c", content='<result id="res_ab" tool="t" lines="9" size="1 KB">\np\n</result>'
        )
        refused = Message(
            role="tool", tool_call_id="c", content='<result tool="t" lines="9" size="1 KB" stored="false" reason="x">'
        )
        assert is_offload_envelope(envelope)
        assert not is_offload_envelope(refused)
        assert not is_offload_envelope(Message(role="tool", tool_call_id="c", content="plain"))


class TestKeepTailStart:
    def test_small_log_fits_entirely(self):
        messages = [user("a"), assistant("b")]
        assert keep_tail_start(messages, 10_000) == 0

    def test_walks_back_to_budget(self):
        messages = [user(long_text(500)) for _ in range(10)]
        start = keep_tail_start(messages, 1_000)
        assert 0 < start < 10
        # The tail it selects stays within an order of the budget.
        assert start >= 7

    def test_injected_pair_not_counted(self, exact_tokens):
        # A giant injected summary between tail messages must not eat the keep budget.
        pair = Message(role="user", content=SUMMARY_PREFIX + long_text(5_000), from_history=True)
        messages = [user(long_text(500)) for _ in range(6)] + [pair] + [user(long_text(500)) for _ in range(2)]
        start = keep_tail_start(messages, 1_500)
        # Tail: the two 500-token users, the (uncounted) pair, and the 500-token user before it.
        assert start == 5


class TestChooseBoundary:
    def test_boundary_is_user_or_assistant(self):
        messages = [user(long_text(400)) for _ in range(6)] + batch("c1", long_text(400)) + [user(long_text(400))]
        boundary = choose_boundary(messages, 800)
        assert boundary is not None
        assert messages[boundary].role in ("user", "assistant")

    def test_tool_candidate_moves_to_batch_head(self, exact_tokens):
        # Two results in one batch; the token walk lands the tail start on the second result.
        head = Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "c1", "function": {"name": "lookup"}}, {"id": "c2", "function": {"name": "lookup"}}],
        )
        result_one = Message(role="tool", tool_call_id="c1", tool_name="lookup", content=long_text(600))
        result_two = Message(role="tool", tool_call_id="c2", tool_name="lookup", content=long_text(600))
        messages = [user(long_text(300)) for _ in range(4)] + [head, result_one, result_two]
        boundary = choose_boundary(messages, 700)  # walk stops on result_two
        assert boundary is not None
        # The whole batch lands in the kept tail: boundary at or before the head.
        assert boundary <= messages.index(head)
        assert messages[boundary].role != "tool"

    def test_interleaved_orphan_detected(self, exact_tokens):
        # head ... unrelated user ... result: a boundary on the user would orphan the result.
        head, result = batch("c9", long_text(600))
        middle = user(long_text(50))
        messages = [user(long_text(400)) for _ in range(5)] + [head, middle, result] + [user(long_text(300))]
        boundary = choose_boundary(messages, 1_000)  # walk stops on middle (300+600+50 > 1000)
        assert boundary is not None
        assert boundary != messages.index(middle)
        assert boundary <= messages.index(head)

    def test_undurable_anchors_skipped(self):
        durable = user(long_text(300))
        messages = (
            [user(long_text(400)) for _ in range(4)]
            + [durable]
            + [user(long_text(200), temporary=True), user(long_text(200), add_to_agent_memory=False)]
            + [user(long_text(300))]
        )
        boundary = choose_boundary(messages, 700)
        assert boundary is not None
        assert not messages[boundary].temporary
        assert messages[boundary].add_to_agent_memory

    def test_injected_pair_never_anchors(self):
        pair = Message(role="user", content=SUMMARY_PREFIX + "old summary", from_history=True)
        messages = [user(long_text(500)) for _ in range(5)] + [pair] + [user(long_text(500)) for _ in range(2)]
        boundary = choose_boundary(messages, 1_200)
        assert boundary is not None
        assert messages[boundary] is not pair

    def test_min_index_respected(self):
        messages = [user(long_text(300)) for _ in range(10)]
        boundary = choose_boundary(messages, 600, min_index=8)
        assert boundary is None or boundary >= 8

    def test_impossible_cut_returns_none(self):
        # Everything in one giant batch: no user/assistant anchor above the floor.
        head, result = batch("c1", long_text(3_000))
        messages = [user("start"), head, result]
        assert choose_boundary(messages, 100, min_index=1) is None

    def test_tool_batch_heads_disallowed_when_scrubbed(self):
        head, result = batch("c1", long_text(50))
        messages = [user(long_text(400)) for _ in range(4)] + [head, result] + [user(long_text(400)) for _ in range(3)]
        allowed = choose_boundary(messages, 1_300, allow_tool_batch_heads=True)
        denied = choose_boundary(messages, 1_300, allow_tool_batch_heads=False)
        if allowed is not None and messages[allowed] is head:
            assert denied is None or messages[denied] is not head

    def test_leading_system_never_cut(self):
        messages = [Message(role="system", content="sys")] + [user(long_text(400)) for _ in range(6)]
        boundary = choose_boundary(messages, 800)
        assert boundary is not None and boundary >= 1


class TestChooseWatermark:
    def test_watermark_at_tail_start(self):
        messages = [user(f"m{i}") for i in range(6)]
        assert choose_watermark(messages, 3) == messages[3].id

    def test_scans_down_past_undurable(self):
        messages = [user("a"), user("b"), user("t", temporary=True), user("d")]
        assert choose_watermark(messages, 2) == messages[1].id

    def test_none_when_nothing_durable(self):
        messages = [user("t", temporary=True), user("u", temporary=True)]
        assert choose_watermark(messages, 1) is None
