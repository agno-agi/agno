"""
Slack HITL Interactions

Handles Slack interaction payloads (button clicks, form submissions) for the HITL system.

Flow:
    Slack webhook POST → router.py → parse_submit_payload() → apply_decisions() → agent resumes

Key functions:
    parse_submit_payload  - Extracts decisions from Slack's nested state structure
    apply_decisions       - Calls requirement.confirm()/reject()/provide_user_input()
    coerce_to_type        - Converts Slack string values to schema types (int, bool, list, dict)
    format_decision_title - Generates task card titles like "Denied: delete_file(path=/tmp)"

Slack payloads have deeply nested state: payload.state.values[block_id][action_id].value
This module handles that extraction so router.py stays focused on HTTP handling.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Type

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

SlackState = Dict[str, Dict[str, Any]]
SlackBlocks = List[Dict[str, Any]]


# --- Type Coercion ---
# Slack form inputs are always strings. These convert to the schema's expected type.


def _coerce_json(raw: str, expected: Type) -> Any:
    parsed = json.loads(raw)
    if not isinstance(parsed, expected):
        raise ValueError(f"expected {expected.__name__}, got {type(parsed).__name__}")
    return parsed


_COERCERS: Dict[Type, Callable[[str], Any]] = {
    str: lambda v: v,
    int: int,
    float: float,
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


# --- Slack State Extraction ---
# Helpers to pull values from Slack's nested state structure.


def _get_action_state(state: SlackState, block_id: str, action_id: str) -> Dict[str, Any]:
    return state.get(block_id, {}).get(action_id, {})


def _extract_text_value(action_state: Dict[str, Any]) -> Optional[str]:
    if action_state.get("type") == "static_select":
        return (action_state.get("selected_option") or {}).get("value")
    return action_state.get("value")


def _extract_selected_values(action_state: Dict[str, Any]) -> List[str]:
    element_type = action_state.get("type")
    if element_type == "checkboxes":
        return [opt["value"] for opt in action_state.get("selected_options", []) if opt.get("value")]
    if element_type == "static_select":
        selected = action_state.get("selected_option") or {}
        return [selected["value"]] if selected.get("value") else []
    return []


# --- Confirmation Parsing ---
# Confirmations store decision in block_id: "row:<req_id>:confirmation:decided:<approve|reject>"


def _find_confirmation_decision(blocks: SlackBlocks, requirement_id: str) -> Optional[str]:
    for block in blocks:
        parsed = parse_row_block_id(block.get("block_id", ""))
        if not parsed:
            continue
        if parsed.get("req_id") != requirement_id:
            continue
        if parsed.get("kind") != "confirmation":
            continue
        if parsed.get("status") == "decided":
            return parsed.get("decided")
    return None


def _parse_confirmation(requirement: RunRequirement, blocks: SlackBlocks) -> ParsedDecision:
    req_id = requirement.id or ""
    decision = _find_confirmation_decision(blocks, req_id)
    if decision is None:
        return ParsedDecision(
            requirement_id=req_id,
            pause_type="confirmation",
            approved=False,
            rejected_note="No decision made",
        )
    return ParsedDecision(
        requirement_id=req_id,
        pause_type="confirmation",
        approved=(decision == "approve"),
    )


# --- User Input Parsing ---
# Each field has block_id: "row:<req_id>:user_input:<field_name>"


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
        raw_value = _extract_text_value(action_state)

        try:
            values[field.name] = coerce_to_type(raw_value, field.field_type)
        except (ValueError, TypeError) as exc:
            errors.append(ParseError(requirement_id=req_id, field=field.name, message=str(exc)))
            values[field.name] = None

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="user_input",
        input_values=values,
    )


# --- User Feedback Parsing ---
# Each question has block_id: "row:<req_id>:user_feedback:q<index>"


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
        picked = _extract_selected_values(action_state)

        if not picked:
            errors.append(ParseError(requirement_id=req_id, field=question.question, message="No option selected"))
        selections[question.question] = picked

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="user_feedback",
        feedback_selections=selections,
    )


# --- External Execution Parsing ---
# Result field has block_id: "row:<req_id>:external_execution:result"


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


# --- Main Entry Points ---


def parse_submit_payload(
    payload: Dict[str, Any],
    requirements: List[RunRequirement],
) -> tuple[List[ParsedDecision], List[ParseError]]:
    blocks: SlackBlocks = (payload.get("message") or {}).get("blocks") or []
    state: SlackState = (payload.get("state") or {}).get("values") or {}

    decisions: List[ParsedDecision] = []
    errors: List[ParseError] = []

    for requirement in requirements:
        kind = classify_requirement(requirement)
        if kind == "confirmation":
            decisions.append(_parse_confirmation(requirement, blocks))
        elif kind == "user_input":
            decisions.append(_parse_user_input(requirement, state, errors))
        elif kind == "user_feedback":
            decisions.append(_parse_user_feedback(requirement, state, errors))
        elif kind == "external_execution":
            decisions.append(_parse_external(requirement, state, errors))

    return decisions, errors


def apply_decisions(decisions: List[ParsedDecision], requirements: List[RunRequirement]) -> None:
    by_id = {r.id: r for r in requirements if r.id}

    for decision in decisions:
        requirement = by_id.get(decision.requirement_id)
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


# --- Decision Title Formatting ---


def _render_value(value: Any) -> str:
    try:
        rendered = value if isinstance(value, str) else json.dumps(value, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return _truncate(rendered.replace("\n", " ").strip(), DECISION_VALUE_MAX)


def _format_args(args: Dict[str, Any]) -> str:
    return ", ".join(f"{k}={_render_value(v)}" for k, v in args.items())


def format_decision_title(decision: ParsedDecision, requirement: RunRequirement) -> str:
    if decision.pause_type != "confirmation":
        raise ValueError("format_decision_title only supports confirmation decisions")

    verb = "Approved" if decision.approved else "Denied"
    name = _tool_name(requirement)
    args = _format_args(_tool_args(requirement))
    title = f"{verb}: {name}({args})" if args else f"{verb}: {name}"
    return _truncate(title, DECISION_TITLE_MAX)
