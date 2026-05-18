from __future__ import annotations

from typing import Dict, Optional, Tuple

from agno.run.requirement import PauseType

# --- Block ID prefixes ---

ROW_BLOCK_PREFIX = "row"
PAUSE_BLOCK_PREFIX = "pause"

# --- Action IDs (Slack returns these on button clicks) ---

ACTION_SUBMIT = "submit_pause"
ACTION_ROW_APPROVE = "row_approve"
ACTION_ROW_REJECT = "row_reject"
ACTION_REJECT_REASON = "reject_reason"
ACTION_FEEDBACK_SELECT = "feedback_select"
ACTION_EXTERNAL_RESULT = "external_result"
ACTION_INPUT_FIELD_PREFIX = "input_field:"


# --- Block ID builders/parsers ---
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


def pause_block_id(run_id: str) -> str:
    return f"{PAUSE_BLOCK_PREFIX}:{run_id}"


def reject_reason_block_id(requirement_id: str) -> str:
    return f"reject_reason:{requirement_id}"


# --- Field-level block/action ID builders ---


def user_input_block_id(requirement_id: str, field_name: str) -> str:
    return f"{row_block_id(requirement_id, 'user_input')}:{field_name}"


def user_input_action_id(field_name: str) -> str:
    return f"{ACTION_INPUT_FIELD_PREFIX}{field_name}"


def user_feedback_block_id(requirement_id: str, question_index: int) -> str:
    return f"{row_block_id(requirement_id, 'user_feedback')}:q{question_index}"


def feedback_action_id(question_index: int) -> str:
    return f"{ACTION_FEEDBACK_SELECT}:{question_index}"


def external_result_block_id(requirement_id: str) -> str:
    return f"{row_block_id(requirement_id, 'external_execution')}:result"


# --- Button value encoders/decoders ---
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
