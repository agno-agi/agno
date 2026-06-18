import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from agno.utils.log import log_warning


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

    # Sticky "did any assistant text reach the wire this run" flag. Set on the
    # first non-empty streamed content and NEVER reset, so workflow completion can
    # tell a streamed final (suppress the recap) from one that never streamed
    # (e.g. stream_executor_events=False -> emit). Sticky, not per-message: an
    # empty content chunk reopening a message after a tool must not clear it.
    streamed_any_text: bool = False

    # Workflow cancellation marker. Set when a WorkflowCancelledEvent is seen so
    # the trailing WorkflowCompletedEvent (content = cancel reason, not an answer)
    # is suppressed instead of rendered as the assistant's reply.
    cancelled: bool = False

    # State delta tracking
    _last_snapshot: Optional[Dict[str, Any]] = field(default=None, repr=False)

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
