from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.run.requirement import PauseType

# Type aliases for Slack payload structures
SlackState = Dict[str, Dict[str, Any]]  # view.state.values from form submissions
SlackBlocks = List[Dict[str, Any]]  # Message block array

if TYPE_CHECKING:
    from agno.run.requirement import RunRequirement


def block_to_dict(block: Any) -> Dict[str, Any]:
    """Convert a Slack block (SDK model, dataclass, or dict) to a plain dict."""
    if hasattr(block, "to_dict"):
        return block.to_dict()
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True, mode="json")
    if is_dataclass(block) and not isinstance(block, type):
        return asdict(block)
    return block if isinstance(block, dict) else {}


# --- Context dataclasses for interaction handlers ---


@dataclass
class RowActionContext:
    # Decoded from button value
    req_id: str
    run_id: str
    awaiting_ts: Optional[str]
    # Extracted from payload
    channel: str
    card_ts: str
    blocks: List[Dict[str, Any]]


@dataclass
class SubmitContext:
    run_id: str
    channel: str
    msg_ts: str
    thread_ts: str
    session_id: str
    awaiting_ts: Optional[str]
    user_id: str
    team_id: Optional[str]
    state_values: SlackState


@dataclass
class RowTransformResult:
    blocks: List[Dict[str, Any]]
    should_auto_submit: bool


@dataclass
class ConfirmationRowSummary:
    pending_ids: set
    has_global_submit: bool


# --- Decision parsing dataclasses ---


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


# Slack buttons have a 2000-char value limit; text fields have 3000-char limits
def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# tool_execution may be None or lack tool_name if requirement is for user_input/feedback
def tool_name(requirement: "RunRequirement") -> str:
    tool = requirement.tool_execution
    return getattr(tool, "tool_name", None) or "tool"


def tool_args(requirement: "RunRequirement") -> Dict[str, Any]:
    tool = requirement.tool_execution
    # Empty dict fallback ensures JSON serialization never fails
    return getattr(tool, "tool_args", None) or {}


# --- Slack state value extractors ---


def extract_field_value(action_state: Dict[str, Any]) -> Optional[str]:
    # Slack nests static_select under selected_option; text inputs use value directly
    if action_state.get("type") == "static_select":
        return (action_state.get("selected_option") or {}).get("value")
    return action_state.get("value")


def extract_feedback_picks(action_state: Dict[str, Any]) -> List[str]:
    # Checkboxes return selected_options list; static_select returns single selected_option
    etype = action_state.get("type")
    if etype == "checkboxes":
        return [opt["value"] for opt in action_state.get("selected_options", []) if opt.get("value")]
    if etype == "static_select":
        selected = action_state.get("selected_option") or {}
        return [selected["value"]] if selected.get("value") else []
    return []
