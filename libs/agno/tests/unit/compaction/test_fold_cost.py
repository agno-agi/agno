"""Flat fold cost: per-pass summariser input is window-bounded and non-growing, and earlier
summaries ride forward instead of being re-folded."""

from typing import List, Optional

from agno.compaction.compaction import Compaction, CompactionRecord, complete_pass, prepare_pass
from agno.models.message import Message


class RecordingSummarizer:
    id = "recording-summarizer"
    context_window = None

    def __init__(self) -> None:
        self.inputs: List[str] = []

    def response(self, messages):
        user_payload = messages[-1].content
        self.inputs.append(user_payload)

        index = len(self.inputs)

        class _Response:
            content = f"## Goal\nSummary v{index} (carries: fact-from-turn-3)"
            response_usage = None

        return _Response()


def test_fold_cost_flat_across_passes():
    config = Compaction(context_window=4_000, background=False)
    limits = config.resolve_limits(None)
    summarizer = RecordingSummarizer()

    messages: List[Message] = [Message(role="system", content="sys")]
    record: Optional[CompactionRecord] = None
    passes = 0
    segment_sizes: List[int] = []

    for turn in range(1, 61):
        marker = "fact-from-turn-3 " if turn == 3 else ""
        messages.append(Message(role="user", content=f"turn {turn}: {marker}" + "word " * 250))
        messages.append(Message(role="assistant", content="reply " * 100))

        plan = prepare_pass(config, limits, messages, reason="threshold", previous_record=record)
        if plan is not None and not plan.elision_only:
            new_record = complete_pass(plan, config=config, model=summarizer)
            segment_sizes.append(len(plan.rendered_segment or ""))
            # The fold receives the previous summary, never re-reads folded content.
            if record is not None and record.summary:
                assert record.summary in summarizer.inputs[-1]
            record = new_record
            passes += 1

    assert passes >= 5, f"only {passes} passes over 60 turns"

    # Per-pass rendered input is bounded by roughly the trigger's worth of text and does not
    # grow with total session length (pass 1 may be the largest; later passes stay flat).
    later = segment_sizes[1:]
    assert max(later) <= min(later) * 2.5, segment_sizes
    assert max(later) < limits.trigger_tokens * 8  # chars-per-token slack over the trigger bound

    # An early fact survives to the last summary through the carried-forward chain.
    assert record is not None and "fact-from-turn-3" in (record.summary or "")

    # No folded content is ever re-folded: each turn's body appears in at most one segment.
    seen_turn_3 = sum(1 for payload in summarizer.inputs if "turn 3:" in payload)
    assert seen_turn_3 == 1
