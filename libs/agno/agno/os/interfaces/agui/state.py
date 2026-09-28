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

    # State delta tracking
    _last_snapshot: Optional[Dict[str, Any]] = field(default=None, repr=False)

    # Run context
    thread_id: str = ""
    run_id: str = ""
    run_state: Optional[Dict[str, Any]] = None

    # Deterministic message ids. Left unset the ids are random, which is all a
    # single-pass stream needs. A replayable stream sets a namespace so that
    # re-translating the same source events mints the same ids and a client
    # that reconnects mid-message keeps receiving events for the message it
    # already opened. The namespace identifies the run, so every connection to
    # one run mints the same ids while two different runs never collide.
    id_namespace: Optional[str] = None
    # Set by a replayable stream, which can begin in the middle of a run and so
    # must not report the end of a tool call whose start it never saw.
    require_started_tool_calls: bool = False
    _id_seed: str = field(default="", repr=False)
    _id_counter: int = field(default=0, repr=False)

    def set_id_seed(self, seed: Any) -> None:
        """Anchor the next ids to the position of the source event being translated."""
        self._id_seed = str(seed)
        self._id_counter = 0

    def new_message_id(self) -> str:
        if self.id_namespace is None:
            return str(uuid.uuid4())
        minted = self._id_counter
        self._id_counter += 1
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.id_namespace}/{self._id_seed}/{minted}"))

    def open_text_message(self) -> str:
        self.text_message_id = self.new_message_id()
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
        self.reasoning_message_id = self.new_message_id()
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
