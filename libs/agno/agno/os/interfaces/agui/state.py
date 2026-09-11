import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from agno.utils.log import log_warning


def _sequence_position(step_index: Any) -> Optional[int]:
    """Where in a sequence a step index says its step ran, if it says that at all.

    The engine numbers a sequence's steps with plain integers and gives a container's
    children a tuple instead, which every container kind does: Parallel, Loop, Steps and
    Condition all build one. So an integer index is the only thing on an event that says
    two steps ran one after the other rather than side by side.
    """
    if isinstance(step_index, bool) or not isinstance(step_index, int):
        return None
    return step_index


@dataclass
class StepSpan:
    """One workflow step, from the engine's start event until its span has been emitted.

    A step's identity and the name the client sees it under are separate things. Identity
    is the step id, position and name together, and decides which step an event belongs
    to. The display name is all AG-UI carries, and the client rejects a second
    STEP_STARTED for a name it already holds open, so a step whose name is already held
    is announced under a distinguished one instead of waiting for the name to come free.
    """

    step_name: Optional[str] = None
    step_id: Optional[str] = None
    parent_step_id: Optional[str] = None
    step_index: Optional[Any] = None

    # The name AG-UI pairs this step's STEP_STARTED and STEP_FINISHED on. Assigned when
    # the step is announced and never changed, so the pair always agrees.
    display_name: str = ""

    # Whether the client has already been sent this step's own output, either because
    # something inside the step streamed it or because closing the step emitted it.
    produced_text: bool = False

    closed: bool = False


@dataclass(frozen=True)
class SpanTransition:
    """One STEP_STARTED or STEP_FINISHED the client is owed, named as the client sees it."""

    step_name: str
    started: bool


@dataclass
class StreamState:
    """Per-stream state for AG-UI event translation.

    Tracks message lifecycle, tool calls, reasoning sessions, and state deltas.
    All handlers receive this object and mutate it as events flow through.

    Text Message Lifecycle:
        CLOSED (initial)      OPEN                   CLOSED
        text_message_id=""    text_message_id=X      text_message_id=X (persists!)
        text_message_open=F   text_message_open=T    text_message_open=F

    The text_message_id persists after close so tool calls can parent to it.
    """

    # Text message tracking
    text_message_id: str = ""
    text_message_open: bool = False

    # Tool call tracking
    active_tool_call_ids: Set[str] = field(default_factory=set)
    ended_tool_call_ids: Set[str] = field(default_factory=set)
    pending_tool_calls_parent_id: str = ""

    # Reasoning tracking
    reasoning_message_id: Optional[str] = None
    reasoning_step_count: int = 0

    # Workflow steps, in the order they opened, each announced to the client and holding
    # its display name until its span has been emitted.
    spans: List[StepSpan] = field(default_factory=list)

    # Ids of steps whose output the client has already been sent. A span is dropped once
    # its transitions are emitted, so a record kept only on the span cannot answer for a
    # step whose completion arrives after that.
    produced_step_ids: Set[str] = field(default_factory=set)

    # State delta tracking
    _last_snapshot: Optional[Dict[str, Any]] = field(default=None, repr=False)

    # The events that closed everything still open, kept after the closing drained this
    # state. A terminal batch is assembled around them and can still be lost whole, so
    # the closings have to outlive the batch for the caller that ends the run instead.
    built_closings: Optional[List[Any]] = field(default=None, repr=False)

    # Run context
    thread_id: str = ""
    run_id: str = ""
    run_state: Optional[Dict[str, Any]] = None

    def open_text_message(self) -> str:
        self.text_message_id = str(uuid.uuid4())
        self.text_message_open = True
        return self.text_message_id

    def close_text_message(self) -> None:
        # ID persists for tool call parenting — only flag changes
        self.text_message_open = False

    def start_tool_call(self, tool_call_id: str) -> None:
        self.active_tool_call_ids.add(tool_call_id)

    def end_tool_call(self, tool_call_id: str) -> None:
        self.active_tool_call_ids.discard(tool_call_id)
        self.ended_tool_call_ids.add(tool_call_id)

    def get_parent_message_id_for_tool_call(self) -> str:
        # pending_tool_calls_parent_id used for sequential tools after message close
        if self.pending_tool_calls_parent_id:
            return self.pending_tool_calls_parent_id
        # text_message_id persists after close
        return self.text_message_id

    def set_pending_tool_calls_parent_id(self, parent_id: str) -> None:
        self.pending_tool_calls_parent_id = parent_id

    def clear_pending_tool_calls_parent_id(self) -> None:
        self.pending_tool_calls_parent_id = ""

    def record_text_delta(self, step_id: Optional[str] = None) -> None:
        """Credit an emitted text delta to the workflow step that produced it.

        The engine stamps a step's id onto the events its executor produces, so an event
        carrying one credits that step and everything containing it. Anything else names
        no step and is credited to none: a guessed owner suppresses the output of the
        step guessed wrong.
        """
        if step_id is None:
            return
        self.produced_step_ids.add(step_id)
        owner = self._find_span_by_id(step_id)
        if owner is not None:
            self._mark_produced(owner)

    def claim_step_output(self, span: Optional[StepSpan], step_id: Optional[str] = None) -> bool:
        """Whether a closing step's output still has to be sent, claiming it if so.

        A span answers for itself, and the steps containing it then own its output too,
        so they must not send it again when they close. A completion matching no span
        has only its step id to answer with: an id credited with text earlier in the run
        names output the client already holds, and anything else is the only copy there
        is of what that step produced.
        """
        if span is None:
            owed = step_id is None or step_id not in self.produced_step_ids
            if step_id is not None:
                self.produced_step_ids.add(step_id)
            return owed
        owed = not span.produced_text
        self._mark_produced(span)
        return owed

    def open_step(
        self,
        step_name: Optional[str] = None,
        step_id: Optional[str] = None,
        parent_step_id: Optional[str] = None,
        step_index: Optional[Any] = None,
    ) -> List[SpanTransition]:
        """Open a workflow step and return the span transitions that follow from it.

        A start for a step already open announces nothing, because the client holds that
        name already. It still says where the run is, so it closes and drains either way.
        """
        already_open = any(
            span.step_name == step_name and span.step_id == step_id and span.step_index == step_index
            for span in self.spans
            if not span.closed
        )
        self._close_steps_the_run_moved_past(parent_step_id, step_index)
        transitions = self._drain_spans()
        if already_open:
            return transitions
        span = StepSpan(
            step_name=step_name,
            step_id=step_id,
            parent_step_id=parent_step_id,
            step_index=step_index,
            display_name=self._free_display_name(step_name or step_id or "Step"),
        )
        self.spans.append(span)
        transitions.append(SpanTransition(step_name=span.display_name, started=True))
        return transitions

    def _free_display_name(self, wanted: str) -> str:
        """A name no announced step still holds, so the client never sees one name twice.

        Sequential steps reusing a name get that name back, because the earlier one has
        finished by then. Concurrent ones are numbered from two, and a number already
        taken by a step genuinely called that is skipped over.
        """
        taken = {span.display_name for span in self.spans}
        if wanted not in taken:
            return wanted
        counter = 2
        while f"{wanted} {counter}" in taken:
            counter += 1
        return f"{wanted} {counter}"

    def close_step(
        self,
        step_name: Optional[str] = None,
        step_id: Optional[str] = None,
        step_index: Optional[Any] = None,
    ) -> Optional[StepSpan]:
        """Mark a workflow step closed and return it, or None when it was never open.

        The span itself is emitted by ``flush_spans``, once the step's own output has
        been sent.
        """
        span = self._find_open_span(step_name, step_id, step_index)
        if span is None:
            return None
        self._close_span(span)
        return span

    def close_all_spans(self) -> List[SpanTransition]:
        """Close every step still open and return every span transition still owed."""
        for span in self.spans:
            span.closed = True
        return self._drain_spans()

    def flush_spans(self) -> List[SpanTransition]:
        """Return the span transitions the closings so far have made emittable."""
        return self._drain_spans()

    def _drain_spans(self) -> List[SpanTransition]:
        """Finish every closed step, innermost first so a container outlives what it holds.

        Spans go by identity, because removing by value drops whichever span happens to
        compare equal rather than the one that closed.
        """
        transitions: List[SpanTransition] = []
        still_open: List[StepSpan] = []
        for span in reversed(self.spans):
            if span.closed:
                transitions.append(SpanTransition(step_name=span.display_name, started=False))
            else:
                still_open.append(span)
        still_open.reverse()
        self.spans = still_open
        return transitions

    def _close_steps_the_run_moved_past(self, parent_step_id: Optional[str], step_index: Optional[Any]) -> None:
        """Close steps a newly started step proves are over.

        A step that failed under a policy of carrying on never gets a completion event,
        so nothing else would ever close it. Its sequence starting a later step is proof
        it is over: steps sharing a parent and numbered by position run one at a time.
        """
        position = _sequence_position(step_index)
        if position is None:
            return
        for span in list(self.spans):
            if span.closed or span.parent_step_id != parent_step_id:
                continue
            span_position = _sequence_position(span.step_index)
            if span_position is not None and span_position < position:
                self._close_span(span)

    def _close_span(self, span: StepSpan) -> None:
        # A step ending ends everything it contains, whether or not the engine says so
        span.closed = True
        for other in self.spans:
            if not other.closed and self._contains(span, other):
                other.closed = True

    def _contains(self, span: StepSpan, candidate: StepSpan) -> bool:
        parent_id = candidate.parent_step_id
        for _ in range(len(self.spans)):
            if parent_id is None:
                return False
            if parent_id == span.step_id:
                return True
            parent = self._find_span_by_id(parent_id)
            if parent is None:
                return False
            parent_id = parent.parent_step_id
        return False

    def _find_span_by_id(self, step_id: Optional[str]) -> Optional[StepSpan]:
        if step_id is None:
            return None
        for span in self.spans:
            if span.step_id == step_id:
                return span
        return None

    def _find_open_span(
        self, step_name: Optional[str], step_id: Optional[str], step_index: Optional[Any]
    ) -> Optional[StepSpan]:
        open_spans = [span for span in self.spans if not span.closed]
        if step_id is not None:
            for span in open_spans:
                if span.step_id == step_id:
                    return span
            # An event that names a step id names one step, so it can only be about a
            # step that never told us its own id. Matching anything else closes a step
            # the engine did not say was over, and everything inside it with it.
            open_spans = [span for span in open_spans if span.step_id is None]
        # Not every completion event carries a step id, so fall back to the position in
        # the run and then to the innermost open step of that name.
        if step_index is not None:
            for span in open_spans:
                if span.step_name == step_name and span.step_index == step_index:
                    return span
        for span in reversed(open_spans):
            if span.step_name == step_name:
                return span
        return None

    def _mark_produced(self, span: StepSpan) -> None:
        # Text produced inside a step is also output of the steps enclosing it, which
        # must not emit it a second time when they close.
        seen: Set[int] = set()
        current: Optional[StepSpan] = span
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            current.produced_text = True
            if current.step_id is not None:
                self.produced_step_ids.add(current.step_id)
            current = self._find_span_by_id(current.parent_step_id)

    def start_reasoning(self) -> str:
        self.reasoning_message_id = str(uuid.uuid4())
        self.reasoning_step_count = 0
        return self.reasoning_message_id

    def ensure_reasoning_started(self) -> Tuple[str, bool]:
        if self.reasoning_message_id is not None:
            return self.reasoning_message_id, False
        return self.start_reasoning(), True

    def next_reasoning_step(self) -> int:
        self.reasoning_step_count += 1
        return self.reasoning_step_count

    def end_reasoning(self) -> None:
        self.reasoning_message_id = None
        self.reasoning_step_count = 0

    def set_state_snapshot(self, state: Dict[str, Any]) -> None:
        self._last_snapshot = copy.deepcopy(state)

    def compute_state_delta(self, current_state: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        if self._last_snapshot is None:
            return None
        try:
            import jsonpatch

            patch = jsonpatch.make_patch(self._last_snapshot, current_state)
            ops = patch.patch
            if not ops:
                return None
            return ops
        except Exception as e:
            log_warning(f"Failed to compute state delta: {e}")
            return None
