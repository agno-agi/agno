from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agno.os.interfaces.slack.builders import classify_requirement
from agno.os.interfaces.slack.types import (
    ACTION_EXTERNAL_RESULT,
    ACTION_FEEDBACK_SELECT,
    ACTION_INPUT_FIELD_PREFIX,
    ParsedDecision,
    ParseError,
    _tool_args,
    _tool_name,
    _truncate,
    parse_row_block_id,
    row_block_id,
)
from agno.run.requirement import RunRequirement

DECISION_TITLE_MAX = 120
DECISION_VALUE_MAX = 40

StateValues = Dict[str, Dict[str, Any]]


def _type_name(field_type: Any) -> str:
    return field_type.__name__ if isinstance(field_type, type) else str(field_type)


def _coerce_input_value(raw: Optional[str], field_type: Any) -> Any:
    if not raw:
        return None

    type_name = _type_name(field_type)
    if type_name == "str":
        return raw
    if type_name == "int":
        return int(raw)
    if type_name == "float":
        return float(raw)
    if type_name == "bool":
        return raw.lower() in {"true", "1", "yes", "y"}
    if type_name == "list":
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError(f"expected list, got {type(parsed).__name__}")
        return parsed
    if type_name == "dict":
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"expected dict, got {type(parsed).__name__}")
        return parsed
    return raw


def _get_action_state(state_values: StateValues, block_id: str, action_id: str) -> Dict[str, Any]:
    return (state_values.get(block_id) or {}).get(action_id) or {}


def _single_value(action_state: Dict[str, Any]) -> Optional[str]:
    if action_state.get("type") == "static_select":
        return (action_state.get("selected_option") or {}).get("value")
    return action_state.get("value")


def _selected_values(action_state: Dict[str, Any]) -> List[str]:
    element_type = action_state.get("type")

    if element_type == "checkboxes":
        return [opt.get("value") for opt in action_state.get("selected_options") or [] if opt.get("value")]

    if element_type == "static_select":
        value = (action_state.get("selected_option") or {}).get("value")
        return [value] if value else []

    return []


def _confirmation_decision(message_blocks: List[Dict[str, Any]], requirement_id: str) -> Optional[str]:
    for block in message_blocks:
        parsed = parse_row_block_id(block.get("block_id") or "")
        if not parsed:
            continue
        if parsed.get("req_id") != requirement_id:
            continue
        if parsed.get("kind") != "confirmation":
            continue
        if parsed.get("status") == "decided":
            return parsed.get("decided")
    return None


def _parse_confirmation(requirement: RunRequirement, message_blocks: List[Dict[str, Any]]) -> ParsedDecision:
    req_id = requirement.id or ""
    decided = _confirmation_decision(message_blocks, req_id)
    if decided is None:
        return ParsedDecision(
            requirement_id=req_id,
            pause_type="confirmation",
            approved=False,
            rejected_note="No decision made",
        )
    return ParsedDecision(
        requirement_id=req_id,
        pause_type="confirmation",
        approved=decided == "approve",
    )


def _parse_user_input(
    requirement: RunRequirement,
    state_values: StateValues,
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    row_prefix = row_block_id(req_id, "user_input")
    values: Dict[str, Any] = {}

    for field in requirement.user_input_schema or []:
        block_id = f"{row_prefix}:{field.name}"
        action_id = f"{ACTION_INPUT_FIELD_PREFIX}{field.name}"
        action_state = _get_action_state(state_values, block_id, action_id)

        try:
            values[field.name] = _coerce_input_value(_single_value(action_state), field.field_type)
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
    state_values: StateValues,
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    row_prefix = row_block_id(req_id, "user_feedback")
    selections: Dict[str, List[str]] = {}

    for index, question in enumerate(requirement.user_feedback_schema or []):
        block_id = f"{row_prefix}:q{index}"
        action_id = f"{ACTION_FEEDBACK_SELECT}:{index}"
        picked = _selected_values(_get_action_state(state_values, block_id, action_id))

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
    state_values: StateValues,
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    block_id = f"{row_block_id(req_id, 'external_execution')}:result"
    action_state = _get_action_state(state_values, block_id, ACTION_EXTERNAL_RESULT)
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
    message_blocks = (payload.get("message") or {}).get("blocks") or []
    state_values = (payload.get("state") or {}).get("values") or {}

    decisions: List[ParsedDecision] = []
    errors: List[ParseError] = []

    for requirement in requirements:
        kind = classify_requirement(requirement)
        if kind == "confirmation":
            decisions.append(_parse_confirmation(requirement, message_blocks))
        elif kind == "user_input":
            decisions.append(_parse_user_input(requirement, state_values, errors))
        elif kind == "user_feedback":
            decisions.append(_parse_user_feedback(requirement, state_values, errors))
        elif kind == "external_execution":
            decisions.append(_parse_external(requirement, state_values, errors))

    return decisions, errors


def apply_decisions(
    decisions: List[ParsedDecision],
    requirements: List[RunRequirement],
) -> None:
    requirements_by_id = {requirement.id: requirement for requirement in requirements if requirement.id}

    for decision in decisions:
        requirement = requirements_by_id.get(decision.requirement_id)
        if requirement is None:
            continue

        if decision.pause_type == "confirmation":
            if decision.approved:
                requirement.confirm()
            else:
                requirement.reject(decision.rejected_note)
        elif decision.pause_type == "user_input" and decision.input_values is not None:
            requirement.provide_user_input(decision.input_values)
        elif decision.pause_type == "user_feedback" and decision.feedback_selections is not None:
            requirement.provide_user_feedback(decision.feedback_selections)
        elif decision.pause_type == "external_execution" and decision.external_result is not None:
            requirement.set_external_execution_result(decision.external_result)


def _render_value(value: Any) -> str:
    try:
        rendered = value if isinstance(value, str) else json.dumps(value, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return _truncate(rendered.replace("\n", " ").strip(), DECISION_VALUE_MAX)


def _inline_args(args: Dict[str, Any]) -> str:
    return ", ".join(f"{key}={_render_value(value)}" for key, value in args.items())


def format_decision_title(decision: ParsedDecision, requirement: RunRequirement) -> str:
    if decision.pause_type != "confirmation":
        raise ValueError("format_decision_title only supports confirmation decisions")

    verb = "Approved" if decision.approved else "Denied"
    base = f"{verb}: {_tool_name(requirement)}"
    inline = _inline_args(_tool_args(requirement))
    return _truncate(f"{base}({inline})" if inline else base, DECISION_TITLE_MAX)
