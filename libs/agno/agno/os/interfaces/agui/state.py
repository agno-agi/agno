import copy
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from agno.utils.log import log_warning

REDACTED_STATE_VALUE = "[REDACTED]"
SENSITIVE_STATE_KEY_NAMES = {
    "apikey",
    "api_key",
    "authorization",
    "credential",
    "db_password",
    "password",
    "passwd",
    "private_key",
    "secret",
    "token",
}
SENSITIVE_STATE_KEY_SUFFIXES = (
    "_api_key",
    "_access_token",
    "_auth_token",
    "_bearer_token",
    "_client_secret",
    "_db_password",
    "_id_token",
    "_private_key",
    "_refresh_token",
    "_session_token",
)
SENSITIVE_STATE_VALUE_PATTERN = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"sk-[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9_]{8,}|"
    r"xox[baprs]-[A-Za-z0-9-]{8,}|"
    r"AIza[A-Za-z0-9_-]{8,})"
)


def _is_sensitive_agui_state_key(key: str) -> bool:
    normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return normalized_key in SENSITIVE_STATE_KEY_NAMES or normalized_key.endswith(SENSITIVE_STATE_KEY_SUFFIXES)


def _redact_agui_state_value(value: Any, key: Optional[str] = None) -> Any:
    if key is not None and _is_sensitive_agui_state_key(key):
        return REDACTED_STATE_VALUE

    if isinstance(value, dict):
        return {k: _redact_agui_state_value(v, str(k)) for k, v in value.items()}

    if isinstance(value, list):
        return [_redact_agui_state_value(item) for item in value]

    if isinstance(value, str) and SENSITIVE_STATE_VALUE_PATTERN.search(value):
        return SENSITIVE_STATE_VALUE_PATTERN.sub(REDACTED_STATE_VALUE, value)

    return value


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

            patch = jsonpatch.make_patch(
                _redact_agui_state_value(self._last_snapshot),
                _redact_agui_state_value(current_state),
            )
            ops = patch.patch
            if not ops:
                return None
            return ops
        except Exception as e:
            log_warning(f"Failed to compute state delta: {e}")
            return None
