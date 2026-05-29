from __future__ import annotations

from typing import Any, Dict, List, Optional

from agno.os.interfaces.slack.ids import (
    ACTION_EXTERNAL_RESULT,
    ACTION_REJECT_REASON,
    decode_row_button_value,
    decode_submit_button_value,
    encode_submit_button_value,
    external_result_block_id,
    feedback_action_id,
    parse_row_block_id,
    reject_reason_block_id,
    user_feedback_block_id,
    user_input_action_id,
    user_input_block_id,
)
from agno.os.interfaces.slack.types import (
    ConfirmationRowSummary,
    ParsedDecision,
    ParseError,
    RowActionContext,
    SlackBlocks,
    SlackState,
    SubmitContext,
    extract_feedback_picks,
    extract_field_value,
    tool_name,
)
from agno.run.requirement import RunRequirement

# --- Slack state helpers ---


def _get_action_state(state: SlackState, block_id: str, action_id: str) -> Dict[str, Any]:
    return state.get(block_id, {}).get(action_id, {})


# --- Pause type parsers ---
# Each parser extracts user decisions from Slack payload for one pause_type.
# Returns ParsedDecision with the resolved values; appends ParseError for validation failures.


# Parses Approve/Deny toggle state from block_id + optional rejection reason from InputBlock
def _parse_confirmation(
    requirement: RunRequirement,
    blocks: SlackBlocks,
    errors: List[ParseError],
    state: Optional[SlackState] = None,
) -> ParsedDecision:
    req_id = requirement.id or ""
    state = state or {}
    decision = None

    for block in blocks:
        parsed = parse_row_block_id(block.get("block_id", ""))
        if parsed and parsed.get("req_id") == req_id and parsed.get("kind") == "confirmation":
            if parsed.get("status") == "decided":
                decision = parsed.get("decided")
                break

    if decision is None:
        name = tool_name(requirement)
        errors.append(ParseError(requirement_id=req_id, field=name, message="Approval decision required"))
        return ParsedDecision(requirement_id=req_id, pause_type="confirmation", approved=None)

    rejected_note = None
    if decision == "deny":
        reason_state = _get_action_state(state, reject_reason_block_id(req_id), ACTION_REJECT_REASON)
        reason_text = (reason_state.get("value") or "").strip()
        if reason_text:
            rejected_note = reason_text

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="confirmation",
        approved=(decision == "approve"),
        rejected_note=rejected_note,
    )


# Parses text/dropdown fields from user_input_schema
def _parse_user_input(requirement: RunRequirement, state: SlackState, errors: List[ParseError]) -> ParsedDecision:
    req_id = requirement.id or ""
    values: Dict[str, Any] = {}

    for field in requirement.user_input_schema or []:
        action_state = _get_action_state(
            state, user_input_block_id(req_id, field.name), user_input_action_id(field.name)
        )
        values[field.name] = extract_field_value(action_state)
        if values[field.name] is None:
            errors.append(ParseError(requirement_id=req_id, field=field.name, message="This field is required"))

    return ParsedDecision(requirement_id=req_id, pause_type="user_input", input_values=values)


# Parses checkbox/dropdown selections from user_feedback_schema questions
def _parse_user_feedback(requirement: RunRequirement, state: SlackState, errors: List[ParseError]) -> ParsedDecision:
    req_id = requirement.id or ""
    selections: Dict[str, List[str]] = {}

    for i, question in enumerate(requirement.user_feedback_schema or []):
        action_state = _get_action_state(state, user_feedback_block_id(req_id, i), feedback_action_id(i))
        picked = extract_feedback_picks(action_state)
        if not picked:
            errors.append(ParseError(requirement_id=req_id, field=question.question, message="No option selected"))
        selections[question.question] = picked

    return ParsedDecision(requirement_id=req_id, pause_type="user_feedback", feedback_selections=selections)


# Parses pasted execution result from external_execution text field
def _parse_external(
    requirement: RunRequirement,
    state: SlackState,
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    action_state = _get_action_state(state, external_result_block_id(req_id), ACTION_EXTERNAL_RESULT)
    result = (action_state.get("value") or "").strip()

    if not result:
        errors.append(ParseError(requirement_id=req_id, field="result", message="Result must be non-empty"))

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="external_execution",
        external_result=result or None,
    )


# --- Context extraction helpers ---


def extract_row_action_context(payload: Dict[str, Any]) -> Optional[RowActionContext]:
    actions = payload.get("actions") or []
    if not actions:
        return None
    button_value = actions[0].get("value") or ""
    if "|" not in button_value:
        return None
    req_id, run_id, awaiting_ts = decode_row_button_value(button_value)

    channel = (payload.get("channel") or {}).get("id")
    message = payload.get("message") or {}
    card_ts = message.get("ts")
    if not channel or not card_ts:
        return None

    return RowActionContext(
        req_id=req_id,
        run_id=run_id,
        awaiting_ts=awaiting_ts,
        channel=channel,
        card_ts=card_ts,
        blocks=list(message.get("blocks") or []),
    )


def extract_submit_context(payload: Dict[str, Any], entity_id: str) -> Optional[SubmitContext]:
    actions = payload.get("actions") or []
    if not actions:
        return None
    submit_block_id = actions[0].get("block_id") or ""
    if not submit_block_id.startswith("pause:"):
        return None
    run_id = submit_block_id.removeprefix("pause:")

    channel = (payload.get("channel") or {}).get("id")
    message = payload.get("message") or {}
    msg_ts = message.get("ts")
    if not (run_id and channel and msg_ts):
        return None

    thread_ts = message.get("thread_ts") or msg_ts
    button_value = actions[0].get("value") or ""
    _, awaiting_ts = decode_submit_button_value(button_value)

    return SubmitContext(
        run_id=run_id,
        channel=channel,
        msg_ts=msg_ts,
        thread_ts=thread_ts,
        session_id=f"{entity_id}:{thread_ts}",
        awaiting_ts=awaiting_ts,
        user_id=(payload.get("user") or {}).get("id", ""),
        team_id=(payload.get("team") or {}).get("id"),
        state_values=(payload.get("state") or {}).get("values") or {},
    )


def confirmation_row_summary(blocks: List[Dict[str, Any]]) -> ConfirmationRowSummary:
    pending_ids: set[str] = set()
    has_global_submit = False
    for block in blocks:
        block_id = block.get("block_id", "")
        block_type = block.get("type", "")
        # Global submit button lives in an actions block with pause: prefix
        if block_type == "actions" and block_id.startswith("pause:"):
            has_global_submit = True
        # Fresh confirmation row not yet decided
        if block_id.startswith("rowact:") and ":confirmation" in block_id:
            if ":selected:" not in block_id and ":decided:" not in block_id:
                parts = block_id.split(":")
                if len(parts) >= 2:
                    pending_ids.add(parts[1])
        # Decision marker removes from pending
        if block_id.startswith("row:") and ":confirmation:decided:" in block_id:
            parts = block_id.split(":")
            if len(parts) >= 2:
                pending_ids.discard(parts[1])
    return ConfirmationRowSummary(pending_ids=pending_ids, has_global_submit=has_global_submit)


def synthetic_submit_payload(
    payload: Dict[str, Any],
    run_id: str,
    awaiting_ts: Optional[str],
    blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    synthetic = dict(payload)
    synthetic["actions"] = [
        {
            "action_id": "submit_pause",
            "block_id": f"pause:{run_id}",
            "value": encode_submit_button_value(run_id, awaiting_ts),
        }
    ]
    synthetic["message"] = {**(payload.get("message") or {}), "blocks": blocks}
    return synthetic


# --- Public API ---


# Entry point: routes each requirement to its pause_type parser
def parse_submit_payload(
    payload: Dict[str, Any],
    requirements: List[RunRequirement],
) -> tuple[List[ParsedDecision], List[ParseError]]:
    blocks: SlackBlocks = (payload.get("message") or {}).get("blocks") or []
    state: SlackState = (payload.get("state") or {}).get("values") or {}

    decisions: List[ParsedDecision] = []
    errors: List[ParseError] = []

    for requirement in requirements:
        kind = requirement.pause_type
        if kind == "confirmation":
            decisions.append(_parse_confirmation(requirement, blocks, errors, state))
        elif kind == "user_input":
            decisions.append(_parse_user_input(requirement, state, errors))
        elif kind == "user_feedback":
            decisions.append(_parse_user_feedback(requirement, state, errors))
        elif kind == "external_execution":
            decisions.append(_parse_external(requirement, state, errors))

    return decisions, errors


# Mutates RunRequirement objects — agent holds refs to these and polls for resolution
def apply_decisions(decisions: List[ParsedDecision], requirements: List[RunRequirement]) -> None:
    by_id = {r.id: r for r in requirements if r.id}

    for d in decisions:
        req = by_id.get(d.requirement_id)
        if req is None:
            continue

        if d.pause_type == "confirmation" and d.approved is True:
            req.confirm()
        elif d.pause_type == "confirmation" and d.approved is False:
            req.reject(d.rejected_note)
        elif d.pause_type == "user_input" and d.input_values is not None:
            req.provide_user_input(d.input_values)
        elif d.pause_type == "user_feedback" and d.feedback_selections is not None:
            req.provide_user_feedback(d.feedback_selections)
        elif d.pause_type == "external_execution" and d.external_result is not None:
            req.set_external_execution_result(d.external_result)
