"""ContextGauge: token accounting for compaction triggers, anchored on provider actuals.

Estimates here are always computed locally (tiktoken or a character heuristic) — never via
provider count_tokens overrides, several of which are network calls per invocation. The gauge
answers "how big is the next call" cheaply at every loop-top: the last assistant message's own
usage numbers anchor the reading, and only messages appended since are estimated.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from agno.compaction.compaction import EffectiveLimits
from agno.models.message import Message


def estimate_tokens(messages: List[Message]) -> int:
    """Local token estimate for a list of messages. Never makes a network call."""
    from agno.utils.tokens import count_tokens

    return count_tokens(list(messages))


def estimate_message_tokens(message: Message) -> int:
    from agno.utils.tokens import count_tokens

    return count_tokens([message])


@dataclass
class ContextGauge:
    """Per-run token gauge. Lives on CompactionRunState — never on the config object.

    Anchor rule: only assistant messages produced by the current loop under the current record are
    observed, so a usage sample can never predate the active boundary; every pass invalidates the
    anchor, since the newest sample then measures the pre-pass context.
    """

    limits: EffectiveLimits
    # Provider actual from the last observed assistant message: input + output tokens.
    anchor_tokens: Optional[int] = None
    anchor_message_id: Optional[str] = None
    # Threshold checks are suppressed until the reading grows past these watermarks.
    suppress_hard_below: Optional[int] = None
    suppress_soft_below: Optional[int] = None
    # The most recent reading, for out-of-loop observers (the compact_status tool).
    last_reading: Optional[int] = None
    _cache: Optional[Tuple[int, Optional[str], int]] = field(default=None, repr=False)

    def observe_actual(self, assistant_message: Message) -> None:
        """Record a provider usage sample from an assistant message the loop just produced."""
        metrics = getattr(assistant_message, "metrics", None)
        if metrics is None:
            return
        total = (metrics.input_tokens or 0) + (metrics.output_tokens or 0)
        if total <= 0:
            return
        self.anchor_tokens = total
        self.anchor_message_id = assistant_message.id
        self._cache = None

    def invalidate_anchor(self) -> None:
        """A pass happened: the newest sample measures the pre-pass context, so drop it."""
        self.anchor_tokens = None
        self.anchor_message_id = None
        self._cache = None

    def reading(self, view_messages: List[Message]) -> int:
        """Estimated tokens of the next provider call for this view.

        Uses the anchor when its message is still in the view (a message absent from the view is
        behind the active boundary, so its sample is rejected); otherwise a pure local estimate.
        """
        if self.anchor_tokens is not None and self.anchor_message_id is not None:
            for index in range(len(view_messages) - 1, -1, -1):
                if view_messages[index].id == self.anchor_message_id:
                    value = self.anchor_tokens + estimate_tokens(view_messages[index + 1 :])
                    self.last_reading = value
                    return value
        cache_key = (len(view_messages), view_messages[-1].id if view_messages else None)
        if self._cache is not None and self._cache[0] == cache_key[0] and self._cache[1] == cache_key[1]:
            self.last_reading = self._cache[2]
            return self._cache[2]
        value = estimate_tokens(view_messages)
        self._cache = (cache_key[0], cache_key[1], value)
        self.last_reading = value
        return value

    def over_hard(self, reading: int) -> bool:
        if reading <= self.limits.trigger_tokens:
            return False
        if self.suppress_hard_below is not None:
            if reading < self.suppress_hard_below:
                return False
            self.suppress_hard_below = None
        return True

    def over_soft(self, reading: int) -> bool:
        if self.limits.soft_trigger_tokens is None or reading <= self.limits.soft_trigger_tokens:
            return False
        if self.suppress_soft_below is not None:
            if reading < self.suppress_soft_below:
                return False
            self.suppress_soft_below = None
        return True

    def suppress_hard(self, post_pass_reading: int) -> None:
        self.suppress_hard_below = post_pass_reading + self.limits.reserve_eff // 2

    def suppress_soft(self, post_pass_reading: int) -> None:
        self.suppress_soft_below = post_pass_reading + self.limits.reserve_eff // 2

    def meets_floor(self, reading: int) -> bool:
        """The worth-it floor for threshold/requested passes; overflow and manual are exempt."""
        return reading >= self.limits.worth_it_floor
