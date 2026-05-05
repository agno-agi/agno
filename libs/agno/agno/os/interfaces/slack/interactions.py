from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Type

from agno.os.interfaces.slack.types import (
    ACTION_EXTERNAL_RESULT,
    ACTION_FEEDBACK_SELECT,
    ACTION_INPUT_FIELD_PREFIX,
    ACTION_REJECT_REASON,
    ParsedDecision,
    ParseError,
    _tool_args,
    _tool_name,
    _truncate,
    parse_row_block_id,
    row_block_id,
)
from agno.run.requirement import RunRequirement

# Slack task card title truncation — longer titles wrap awkwardly in the plan block
DECISION_TITLE_MAX = 120
# Slack Card body renders poorly with long values; keeps single-line args readable
DECISION_VALUE_MAX = 40

SlackState = Dict[str, Dict[str, Any]]
SlackBlocks = List[Dict[str, Any]]


def _coerce_json(raw: str, expected: Type) -> Any:
    parsed = json.loads(raw)
    if not isinstance(parsed, expected):
        raise ValueError(f"expected {expected.__name__}, got {type(parsed).__name__}")
    return parsed


# Slack input fields always return strings; coerce back to schema-declared types
_COERCERS: Dict[Type, Callable[[str], Any]] = {
    str: lambda v: v,
    int: int,
    float: float,
    # Slack has no native boolean input; users type "true"/"1"/"yes" in plain_text_input
    bool: lambda v: v.lower() in ("true", "1", "yes"),
    list: lambda v: _coerce_json(v, list),
    dict: lambda v: _coerce_json(v, dict),
}


def coerce_to_type(raw: Optional[str], target_type: Type) -> Any:
    if not raw:
        return None
    coercer = _COERCERS.get(target_type)
    if coercer is None:
        return raw
    return coercer(raw)


def _get_action_state(state: SlackState, block_id: str, action_id: str) -> Dict[str, Any]:
    return state.get(block_id, {}).get(action_id, {})


def _parse_confirmation(
    requirement: RunRequirement,
    blocks: SlackBlocks,
    errors: List[ParseError],
    state: SlackState = None,
) -> ParsedDecision:
    req_id = requirement.id or ""
    state = state or {}
    # Confirmation state lives in block_id, not view state — button clicks update the block itself
    decision = None
    rejected_note: Optional[str] = None

    for block in blocks:
        parsed = parse_row_block_id(block.get("block_id", ""))
        if parsed and parsed.get("req_id") == req_id and parsed.get("kind") == "confirmation":
            if parsed.get("status") == "decided":
                decision = parsed.get("decided")

        # Extract rejection note from embedded context block (legacy format)
        block_id = block.get("block_id", "")
        if block_id == f"reject_note:{req_id}":
            elements = block.get("elements") or []
            if elements:
                note_text = elements[0].get("text", "").strip()
                if note_text:
                    rejected_note = note_text

    # Also check for rejection reason from InputBlock state (toggle format)
    if rejected_note is None:
        reason_state = _get_action_state(state, f"reject_reason:{req_id}", ACTION_REJECT_REASON)
        reason_text = (reason_state.get("value") or "").strip()
        if reason_text:
            rejected_note = reason_text

    if decision is None:
        # Undecided confirmation is a validation error, not an implicit rejection
        tool_name = _tool_name(requirement)
        errors.append(ParseError(requirement_id=req_id, field=tool_name, message="Approval decision required"))
        return ParsedDecision(
            requirement_id=req_id,
            pause_type="confirmation",
            approved=None,
        )
    return ParsedDecision(
        requirement_id=req_id,
        pause_type="confirmation",
        approved=(decision == "approve"),
        rejected_note=rejected_note,
    )


def _parse_user_input(
    requirement: RunRequirement,
    state: SlackState,
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    row_prefix = row_block_id(req_id, "user_input")
    values: Dict[str, Any] = {}

    for field in requirement.user_input_schema or []:
        block_id = f"{row_prefix}:{field.name}"
        action_id = f"{ACTION_INPUT_FIELD_PREFIX}{field.name}"
        action_state = _get_action_state(state, block_id, action_id)
        # Slack nests static_select values under selected_option; text inputs use value directly
        if action_state.get("type") == "static_select":
            raw_value = (action_state.get("selected_option") or {}).get("value")
        else:
            raw_value = action_state.get("value")

        try:
            values[field.name] = coerce_to_type(raw_value, field.field_type)
            # All user_input fields are required — None means empty submission
            if values[field.name] is None:
                errors.append(ParseError(requirement_id=req_id, field=field.name, message="This field is required"))
        except (ValueError, TypeError) as exc:
            errors.append(ParseError(requirement_id=req_id, field=field.name, message=str(exc)))
            values[field.name] = None

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="user_input",
        input_values=values,
    )


def _parse_user_feedback(
    requirement: RunRequirement,
    state: SlackState,
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    row_prefix = row_block_id(req_id, "user_feedback")
    selections: Dict[str, List[str]] = {}

    for index, question in enumerate(requirement.user_feedback_schema or []):
        block_id = f"{row_prefix}:q{index}"
        action_id = f"{ACTION_FEEDBACK_SELECT}:{index}"
        action_state = _get_action_state(state, block_id, action_id)
        # Checkboxes return list of selected_options; static_select returns single selected_option
        element_type = action_state.get("type")
        if element_type == "checkboxes":
            picked = [opt["value"] for opt in action_state.get("selected_options", []) if opt.get("value")]
        elif element_type == "static_select":
            selected = action_state.get("selected_option") or {}
            picked = [selected["value"]] if selected.get("value") else []
        else:
            picked = []

        if not picked:
            errors.append(ParseError(requirement_id=req_id, field=question.question, message="No option selected"))
        selections[question.question] = picked

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="user_feedback",
        feedback_selections=selections,
    )


def _parse_external(
    requirement: RunRequirement,
    state: SlackState,
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    block_id = f"{row_block_id(req_id, 'external_execution')}:result"
    action_state = _get_action_state(state, block_id, ACTION_EXTERNAL_RESULT)
    result = (action_state.get("value") or "").strip()

    if not result:
        errors.append(ParseError(requirement_id=req_id, field="result", message="Result must be non-empty"))

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="external_execution",
        external_result=result or None,
    )


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


def apply_decisions(decisions: List[ParsedDecision], requirements: List[RunRequirement]) -> None:
    # Mutate original RunRequirement objects — the agent holds refs to these and polls for resolution
    by_id = {r.id: r for r in requirements if r.id}

    for decision in decisions:
        requirement = by_id.get(decision.requirement_id)
        if requirement is None:
            continue

        if decision.pause_type == "confirmation":
            if decision.approved is True:
                requirement.confirm()
            elif decision.approved is False:
                requirement.reject(decision.rejected_note)
            # approved=None means undecided — skip, validation error already recorded
        elif decision.pause_type == "user_input" and decision.input_values is not None:
            requirement.provide_user_input(decision.input_values)
        elif decision.pause_type == "user_feedback" and decision.feedback_selections is not None:
            requirement.provide_user_feedback(decision.feedback_selections)
        elif decision.pause_type == "external_execution" and decision.external_result is not None:
            requirement.set_external_execution_result(decision.external_result)


def format_decision_title(decision: ParsedDecision, requirement: RunRequirement) -> str:
    # Only confirmation decisions have a meaningful approve/deny verb to display
    if decision.pause_type != "confirmation":
        raise ValueError("format_decision_title only supports confirmation decisions")

    verb = "Approved" if decision.approved else "Denied"
    name = _tool_name(requirement)
    args_dict = _tool_args(requirement)
    arg_parts = []
    for k, v in args_dict.items():
        try:
            rendered = v if isinstance(v, str) else json.dumps(v, default=str)
        except (TypeError, ValueError):
            rendered = str(v)
        # Collapse newlines so multi-line JSON renders as single-line in the card header
        rendered = _truncate(rendered.replace("\n", " ").strip(), DECISION_VALUE_MAX)
        arg_parts.append(f"{k}={rendered}")
    args = ", ".join(arg_parts)
    title = f"{verb}: {name}({args})" if args else f"{verb}: {name}"
    # Slack plan block wraps awkwardly on long titles; truncate to keep it single-line
    return _truncate(title, DECISION_TITLE_MAX)
