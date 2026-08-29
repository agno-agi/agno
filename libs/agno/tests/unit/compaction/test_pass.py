"""Pass orchestration: prepare (elide-then-fold decision), complete, chain storage, registry."""

import threading

import pytest

from agno.compaction._notice import NoticeInputs
from agno.compaction._state import FoldHandle, clear_fold, in_flight_fold, register_fold
from agno.compaction._tokens import estimate_tokens
from agno.compaction._view import build_view
from agno.compaction.compaction import (
    Compaction,
    CompactionRecord,
    acomplete_pass,
    complete_pass,
    get_owner_records,
    merge_records_into_session_data,
    prepare_pass,
    resolve_active_record,
)
from agno.models.message import Message


class StubModel:
    id = "stub-summarizer"

    def __init__(self, reply="## Goal\nStub summary."):
        self.reply = reply
        self.calls = []

    def response(self, messages):
        self.calls.append(messages)

        class _Response:
            content = self.reply
            response_usage = None

        return _Response()

    async def aresponse(self, messages):
        return self.response(messages)


def user(text, **kwargs):
    return Message(role="user", content=text, **kwargs)


def long_text(tokens):
    return "word " * tokens


def tool_batch(call_id, result_tokens, name="lookup"):
    return [
        Message(role="assistant", content=None, tool_calls=[{"id": call_id, "function": {"name": name}}]),
        Message(role="tool", tool_call_id=call_id, tool_name=name, content=long_text(result_tokens)),
    ]


def small_config():
    # 2_000-token window: reserve_eff=250, keep_eff=500, trigger=1_700, soft=1_400.
    config = Compaction(context_window=2_000)
    return config, config.resolve_limits(None)


class TestPreparePass:
    def test_elision_only_when_elision_suffices(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")]
        for index in range(4):
            messages += tool_batch(f"c{index}", 500)
        messages.append(user(long_text(100)))
        plan = prepare_pass(config, limits, messages, reason="threshold")
        assert plan is not None
        assert plan.elision_only
        assert plan.watermark_id is not None
        assert plan.boundary_index is None
        trial = CompactionRecord.create("threshold")
        trial.elision_watermark_message_id = plan.watermark_id
        assert estimate_tokens(build_view(messages, trial)) <= limits.trigger_tokens

    def test_fold_when_elision_not_enough(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")] + [user(long_text(300)) for _ in range(10)]
        plan = prepare_pass(config, limits, messages, reason="threshold")
        assert plan is not None
        assert not plan.elision_only
        assert plan.boundary_index is not None
        assert plan.boundary_message_id == messages[plan.boundary_index].id
        assert plan.rendered_segment and "word" in plan.rendered_segment
        assert "sys" not in plan.rendered_segment

    def test_previous_summary_and_segment_start(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")] + [user(f"early {long_text(300)}") for _ in range(3)]
        previous = CompactionRecord.create("threshold")
        previous.summary = "## Goal\nEarlier work."
        previous.first_kept_message_id = messages[2].id
        messages += [user(f"later {long_text(300)}") for _ in range(8)]
        plan = prepare_pass(config, limits, messages, reason="threshold", previous_record=previous)
        assert plan is not None and not plan.elision_only
        assert plan.previous_summary == "## Goal\nEarlier work."
        # The segment starts at the previous boundary: message 1 (before it) is not re-folded.
        assert "early" not in (plan.rendered_segment or "") or plan.rendered_segment.count("early") < 3
        assert plan.boundary_index > 2

    def test_unresolvable_previous_record_treated_absent(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")] + [user(long_text(300)) for _ in range(10)]
        previous = CompactionRecord.create("threshold")
        previous.summary = "old"
        previous.first_kept_message_id = "msg-gone"
        plan = prepare_pass(config, limits, messages, reason="threshold", previous_record=previous)
        assert plan is not None
        assert plan.previous_summary is None

    def test_under_trigger_with_no_elision_advance_is_noop(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys"), user("tiny")]
        assert prepare_pass(config, limits, messages, reason="threshold") is None

    def test_manual_always_folds(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")] + [user(long_text(300)) for _ in range(4)]
        plan = prepare_pass(config, limits, messages, reason="manual")
        assert plan is not None
        assert not plan.elision_only

    def test_manual_with_empty_pre_tail_returns_none(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys"), user("only message")]
        assert prepare_pass(config, limits, messages, reason="manual") is None

    def test_min_boundary_index_enforced(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")] + [user(long_text(300)) for _ in range(10)]
        plan = prepare_pass(config, limits, messages, reason="threshold", min_boundary_index=8)
        assert plan is None or plan.elision_only or plan.boundary_index >= 8

    def test_watermark_monotonic_against_previous(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")]
        for index in range(4):
            messages += tool_batch(f"c{index}", 400)
        messages.append(user(long_text(50)))
        previous = CompactionRecord.create("threshold")
        previous.elision_watermark_message_id = messages[-1].id  # already past everything
        plan = prepare_pass(config, limits, messages, reason="threshold", previous_record=previous)
        if plan is not None:
            assert plan.watermark_id == messages[-1].id

    def test_notice_generated_from_inputs(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")] + [user(long_text(300)) for _ in range(10)]
        inputs = NoticeInputs(result_ids=["res_ab12"], variables=["frames"])
        plan = prepare_pass(config, limits, messages, reason="threshold", notice_inputs=inputs)
        assert plan is not None
        assert "res_ab12" in (plan.notice or "")


class TestCompletePass:
    def _fold_plan(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")] + [user(long_text(300)) for _ in range(10)]
        plan = prepare_pass(config, limits, messages, reason="threshold", created_by_run_id="run-9")
        assert plan is not None and not plan.elision_only
        return config, plan

    def test_fold_record(self):
        config, plan = self._fold_plan()
        model = StubModel()
        record = complete_pass(plan, config=config, model=model)
        assert record.summary == "## Goal\nStub summary."
        assert record.first_kept_message_id == plan.boundary_message_id
        assert record.created_by_run_id == "run-9"
        assert record.stats["summarizer_model_id"] == "stub-summarizer"
        assert record.stats["tokens_before"] == plan.tokens_before
        assert len(model.calls) == 1

    def test_fold_record_estimates_tokens_after(self):
        # Records that never activate in-run (build-time and next-run commits) still carry a
        # usable tokens_after: the kept slice plus the injected summary pair, estimated at
        # completion. An in-run activation later overwrites it with the gauge's live reading.
        config, plan = self._fold_plan()
        record = complete_pass(plan, config=config, model=StubModel())
        tokens_after = record.stats["tokens_after"]
        assert tokens_after is not None and tokens_after > 0
        assert tokens_after < plan.tokens_before

    def test_elision_only_record_estimates_tokens_after(self):
        config, limits = small_config()
        messages = [Message(role="system", content="sys")]
        for index in range(4):
            messages += tool_batch(f"c{index}", 500)
        messages.append(user(long_text(100)))
        plan = prepare_pass(config, limits, messages, reason="threshold")
        assert plan is not None and plan.elision_only
        record = complete_pass(plan, config=config, model=None)
        tokens_after = record.stats["tokens_after"]
        assert tokens_after is not None and 0 < tokens_after <= limits.trigger_tokens
        assert tokens_after < plan.tokens_before

    def test_async_twin(self):
        import asyncio

        config, plan = self._fold_plan()
        record = asyncio.run(acomplete_pass(plan, config=config, model=StubModel()))
        assert record.summary == "## Goal\nStub summary."

    def test_elision_only_copies_predecessor(self):
        config, limits = small_config()
        previous = CompactionRecord.create("threshold")
        previous.summary = "kept summary"
        previous.first_kept_run_id = "run-1"
        previous.first_kept_message_id = "msg-1"
        plan_messages = [Message(role="system", content="sys")]
        plan = prepare_pass(config, limits, plan_messages, reason="threshold")
        assert plan is None  # nothing to do on an empty log
        from agno.compaction.compaction import PassPlan

        elision_plan = PassPlan(
            reason="threshold",
            created_by_run_id=None,
            previous_record=previous,
            elision_only=True,
            watermark_id="msg-5",
            boundary_index=None,
            boundary_message_id=None,
            rendered_segment=None,
            previous_summary=previous.summary,
            notice=None,
            tokens_before=100,
        )
        record = complete_pass(elision_plan, config=config, model=None)
        assert record.summary == "kept summary"
        assert record.first_kept_run_id == "run-1"
        assert record.first_kept_message_id == "msg-1"
        assert record.elision_watermark_message_id == "msg-5"
        assert record.previous_id == previous.id

    def test_fold_without_model_raises(self):
        config, plan = self._fold_plan()
        with pytest.raises(ValueError, match="summariser model"):
            complete_pass(plan, config=config, model=None)


class TestChainStorage:
    def test_round_trip_and_owner_isolation(self):
        session_data = {}
        record_a = CompactionRecord.create("threshold")
        record_b = CompactionRecord.create("manual")
        merge_records_into_session_data(session_data, "agent-1", [record_a])
        merge_records_into_session_data(session_data, "agent-2", [record_b])
        assert [r.id for r in get_owner_records(session_data, "agent-1")] == [record_a.id]
        assert [r.id for r in get_owner_records(session_data, "agent-2")] == [record_b.id]
        assert get_owner_records(session_data, "agent-3") == []
        assert get_owner_records(None, "agent-1") == []

    def test_merge_unions_by_id(self):
        session_data = {}
        record_a = CompactionRecord(id="cmp_a", created_at=10)
        record_b = CompactionRecord(id="cmp_b", created_at=5)
        merge_records_into_session_data(session_data, "o", [record_a])
        # A concurrent writer landed record_b in the row; our next merge must keep both.
        merge_records_into_session_data(session_data, "o", [record_b, record_a])
        chain = get_owner_records(session_data, "o")
        assert [r.id for r in chain] == ["cmp_b", "cmp_a"]

    def test_resolve_walks_back_past_invalid(self):
        newest = CompactionRecord(id="cmp_c", created_at=30, created_by_run_id="bad-run")
        middle = CompactionRecord(id="cmp_b", created_at=20)
        oldest = CompactionRecord(id="cmp_a", created_at=10)
        chain = [oldest, middle, newest]
        active = resolve_active_record(chain, record_is_valid=lambda r: r.created_by_run_id is None)
        assert active is middle
        assert resolve_active_record(chain, record_is_valid=lambda r: False) is None

    def test_resolve_tolerates_predicate_errors(self):
        record = CompactionRecord(id="cmp_a", created_at=10)

        def explode(r):
            raise RuntimeError("boom")

        assert resolve_active_record([record], record_is_valid=explode) is None


class TestInFlightRegistry:
    def test_single_slot_per_owner(self):
        gate = threading.Event()
        thread = threading.Thread(target=gate.wait)
        thread.start()
        from agno.compaction.compaction import PassPlan

        plan = PassPlan(
            reason="threshold",
            created_by_run_id=None,
            previous_record=None,
            elision_only=True,
            watermark_id=None,
            boundary_index=None,
            boundary_message_id=None,
            rendered_segment=None,
            previous_summary=None,
            notice=None,
            tokens_before=0,
        )
        handle = FoldHandle(plan=plan, thread=thread)
        try:
            assert register_fold("s1", "o1", handle)
            assert not register_fold("s1", "o1", FoldHandle(plan=plan, thread=thread))
            assert register_fold("s1", "o2", FoldHandle(plan=plan))  # other owner unaffected
            assert in_flight_fold("s1", "o1") is handle
        finally:
            gate.set()
            thread.join()
        clear_fold("s1", "o1", handle)
        # After clearing, the slot is free again.
        assert register_fold("s1", "o1", FoldHandle(plan=plan))
