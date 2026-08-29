"""ContextGauge: actuals anchoring, positional/temporal guards, suppression watermarks."""

from agno.compaction._tokens import ContextGauge, estimate_tokens
from agno.compaction.compaction import Compaction
from agno.models.message import Message


def make_gauge(window=200_000):
    return ContextGauge(limits=Compaction().resolve_limits(window))


def assistant_with_usage(input_tokens, output_tokens, content="reply"):
    message = Message(role="assistant", content=content)
    message.metrics.input_tokens = input_tokens
    message.metrics.output_tokens = output_tokens
    return message


class TestReading:
    def test_full_estimate_without_anchor(self):
        gauge = make_gauge()
        messages = [Message(role="user", content="hello world")]
        assert gauge.reading(messages) == estimate_tokens(messages)

    def test_anchor_plus_delta(self):
        gauge = make_gauge()
        anchor = assistant_with_usage(50_000, 500)
        gauge.observe_actual(anchor)
        appended = Message(role="user", content="follow up question")
        view = [Message(role="user", content="x"), anchor, appended]
        assert gauge.reading(view) == 50_500 + estimate_tokens([appended])

    def test_anchor_rejected_when_absent_from_view(self):
        # An anchor message behind the boundary is not in the view: its sample must be rejected.
        gauge = make_gauge()
        anchor = assistant_with_usage(120_000, 1_000)
        gauge.observe_actual(anchor)
        view = [Message(role="user", content="short view")]
        assert gauge.reading(view) == estimate_tokens(view)

    def test_zero_usage_not_observed(self):
        gauge = make_gauge()
        gauge.observe_actual(Message(role="assistant", content="no usage"))
        assert gauge.anchor_tokens is None

    def test_invalidate_anchor(self):
        gauge = make_gauge()
        anchor = assistant_with_usage(120_000, 1_000)
        gauge.observe_actual(anchor)
        gauge.invalidate_anchor()
        view = [anchor]
        assert gauge.reading(view) == estimate_tokens(view)


class TestTriggers:
    def test_over_hard(self):
        gauge = make_gauge()
        assert not gauge.over_hard(170_000)
        assert gauge.over_hard(170_001)

    def test_over_soft(self):
        gauge = make_gauge()
        assert not gauge.over_soft(140_000)
        assert gauge.over_soft(140_001)

    def test_soft_disabled_without_background(self):
        gauge = ContextGauge(limits=Compaction(background=False).resolve_limits(200_000))
        assert not gauge.over_soft(199_999)

    def test_hard_suppression_until_regrowth(self):
        gauge = make_gauge()
        gauge.suppress_hard(171_000)  # still-over pass: suppressed until +reserve_eff/2
        assert not gauge.over_hard(172_000)
        threshold = 171_000 + gauge.limits.reserve_eff // 2
        assert gauge.over_hard(threshold)
        # Suppression clears once crossed.
        assert gauge.suppress_hard_below is None

    def test_soft_suppression_until_regrowth(self):
        gauge = make_gauge()
        gauge.suppress_soft(150_000)
        assert not gauge.over_soft(151_000)
        assert gauge.over_soft(150_000 + gauge.limits.reserve_eff // 2)

    def test_meets_floor(self):
        gauge = make_gauge()
        assert not gauge.meets_floor(39_999)
        assert gauge.meets_floor(40_000)
