from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.run.requirement import PauseType

if TYPE_CHECKING:
    from agno.run.requirement import RunRequirement


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


ROW_BLOCK_PREFIX = "row"
PAUSE_BLOCK_PREFIX = "pause"

ACTION_SUBMIT = "submit_pause"
ACTION_ROW_APPROVE = "row_approve"
ACTION_ROW_REJECT = "row_reject"
ACTION_REJECT_CONFIRM = "reject_confirm"
ACTION_REJECT_CANCEL = "reject_cancel"
ACTION_REJECT_REASON = "reject_reason"
ACTION_FEEDBACK_SELECT = "feedback_select"
ACTION_EXTERNAL_RESULT = "external_result"
ACTION_INPUT_FIELD_PREFIX = "input_field:"


# Block IDs encode row:req_id:kind:status[:decided] — Slack returns block_id on interactions,
# so we embed all routing info to avoid server-side lookups
def row_block_id(requirement_id: str, kind: PauseType, *, decided: Optional[str] = None) -> str:
    base = f"{ROW_BLOCK_PREFIX}:{requirement_id}:{kind}:pending"
    if decided is None:
        return base
    return f"{ROW_BLOCK_PREFIX}:{requirement_id}:{kind}:decided:{decided}"


def parse_row_block_id(block_id: str) -> Optional[Dict[str, str]]:
    if not block_id.startswith(f"{ROW_BLOCK_PREFIX}:"):
        return None
    # Limit split to 4 so decided value (which may contain colons) stays intact
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


# Slack buttons have a 2000-char value limit; text fields have 3000-char limits
def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# tool_execution may be None or lack tool_name if requirement is for user_input/feedback
def _tool_name(requirement: "RunRequirement") -> str:
    tool = requirement.tool_execution
    return getattr(tool, "tool_name", None) or "tool"


def _tool_args(requirement: "RunRequirement") -> Dict[str, Any]:
    tool = requirement.tool_execution
    # Empty dict fallback ensures JSON serialization never fails
    return getattr(tool, "tool_args", None) or {}


# Pipe-delimited because Slack button values are opaque strings, not JSON — simpler to parse
def encode_row_button_value(req_id: str, run_id: str, awaiting_ts: Optional[str]) -> str:
    return f"{req_id}|{run_id}|{awaiting_ts or ''}"


def decode_row_button_value(value: str) -> Tuple[str, str, Optional[str]]:
    # Limit split to 2 so awaiting_ts (which may contain pipes in edge cases) stays intact
    parts = value.split("|", 2)
    if len(parts) == 2:
        return parts[0], parts[1], None
    if len(parts) == 3:
        return parts[0], parts[1], parts[2] or None
    return "", "", None


def encode_submit_button_value(run_id: str, awaiting_ts: Optional[str]) -> str:
    return f"{run_id}|{awaiting_ts or ''}"


def decode_submit_button_value(value: str) -> Tuple[str, Optional[str]]:
    # Limit split to 1 so awaiting_ts stays intact
    parts = value.split("|", 1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1] or None


def encode_reject_card_value(
    req_id: str, run_id: str, awaiting_ts: Optional[str], original_title: str, original_subtitle: str
) -> str:
    # Base64-encode title/subtitle to avoid delimiter collisions
    import base64

    title_b64 = base64.b64encode(original_title.encode()).decode()
    subtitle_b64 = base64.b64encode(original_subtitle.encode()).decode()
    return f"{req_id}|{run_id}|{awaiting_ts or ''}|{title_b64}|{subtitle_b64}"


def decode_reject_card_value(value: str) -> Tuple[str, str, Optional[str], str, str]:
    import base64

    parts = value.split("|", 4)
    if len(parts) < 5:
        return "", "", None, "", ""
    req_id, run_id, awaiting_ts, title_b64, subtitle_b64 = parts
    try:
        original_title = base64.b64decode(title_b64).decode()
        original_subtitle = base64.b64decode(subtitle_b64).decode()
    except Exception:
        original_title, original_subtitle = "", ""
    return req_id, run_id, awaiting_ts or None, original_title, original_subtitle
