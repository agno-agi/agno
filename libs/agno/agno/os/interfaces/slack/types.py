from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from agno.run.requirement import RunRequirement

PauseType = Literal["confirmation", "user_input", "user_feedback", "external_execution"]


@dataclass
class ParsedDecision:
    requirement_id: str
    pause_type: PauseType
    approved: Optional[bool] = None
    rejected_note: Optional[str] = None
    input_values: Optional[Dict[str, Any]] = None
    feedback_selections: Optional[Dict[str, List[str]]] = None
    external_result: Optional[str] = None


@dataclass
class ParseError:
    requirement_id: str
    field: str
    message: str


@dataclass
class LiveStream:
    channel: str
    thread_ts: str
    recipient_user_id: Optional[str]
    recipient_team_id: Optional[str]
    task_display_mode: str
    buffer_size: int
    awaiting_message_ts: Optional[str] = None
    saved_at: float = field(default_factory=time.monotonic)


ROW_BLOCK_PREFIX = "row"
PAUSE_BLOCK_PREFIX = "pause"

ACTION_SUBMIT = "submit_pause"
ACTION_ROW_APPROVE = "row_approve"
ACTION_ROW_REJECT = "row_reject"
ACTION_FEEDBACK_SELECT = "feedback_select"
ACTION_EXTERNAL_RESULT = "external_result"
ACTION_INPUT_FIELD_PREFIX = "input_field:"


def row_block_id(requirement_id: str, kind: PauseType, *, decided: Optional[str] = None) -> str:
    base = f"{ROW_BLOCK_PREFIX}:{requirement_id}:{kind}:pending"
    if decided is None:
        return base
    return f"{ROW_BLOCK_PREFIX}:{requirement_id}:{kind}:decided:{decided}"


def parse_row_block_id(block_id: str) -> Optional[Dict[str, str]]:
    if not block_id.startswith(f"{ROW_BLOCK_PREFIX}:"):
        return None
    parts = block_id.split(":", 4)
    if len(parts) < 4:
        return None
    out: Dict[str, str] = {
        "req_id": parts[1],
        "kind": parts[2],
        "status": parts[3],
    }
    if len(parts) == 5 and parts[3] == "decided":
        out["decided"] = parts[4]
    return out


def pause_block_id(approval_id: str) -> str:
    return f"{PAUSE_BLOCK_PREFIX}:{approval_id}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _tool_name(requirement: "RunRequirement") -> str:
    tool = requirement.tool_execution
    return getattr(tool, "tool_name", None) or "tool"


def _tool_args(requirement: "RunRequirement") -> Dict[str, Any]:
    tool = requirement.tool_execution
    return getattr(tool, "tool_args", None) or {}
