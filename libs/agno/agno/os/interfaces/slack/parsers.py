from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from agno.os.interfaces.slack.types import (
    ACTION_EXTERNAL_RESULT,
    ACTION_FEEDBACK_SELECT,
    ACTION_INPUT_FIELD_PREFIX,
    ParsedDecision,
    ParseError,
    PauseType,
    parse_row_block_id,
    row_block_id,
)
from agno.run.requirement import RunRequirement

DECISION_TITLE_MAX = 120
DECISION_VALUE_MAX = 40


def _coerce_input_value(raw: Optional[str], field_type: Any) -> Any:
    if raw is None or raw == "":
        return None
    type_name = field_type.__name__ if isinstance(field_type, type) else str(field_type)
    if type_name == "str":
        return raw
    if type_name == "int":
        return int(raw)
    if type_name == "float":
        return float(raw)
    if type_name == "bool":
        return raw.lower() in ("true", "1", "yes", "y")
    if type_name in ("list", "dict"):
        parsed = json.loads(raw)
        if type_name == "list" and not isinstance(parsed, list):
            raise ValueError(f"expected list, got {type(parsed).__name__}")
        if type_name == "dict" and not isinstance(parsed, dict):
            raise ValueError(f"expected dict, got {type(parsed).__name__}")
        return parsed
    return raw


def _decided_from_blocks(message_blocks: List[Dict[str, Any]], requirement_id: str) -> Optional[str]:
    approval_tid = f"approval:{requirement_id}"
    for block in message_blocks:
        if block.get("type") == "plan":
            for task in block.get("tasks") or []:
                if task.get("task_id") != approval_tid:
                    continue
                status = task.get("status")
                if status == "complete":
                    return "approve"
                if status == "error":
                    return "reject"
                return None
        bid = block.get("block_id") or ""
        parsed = parse_row_block_id(bid)
        if not parsed:
            continue
        if parsed.get("req_id") != requirement_id:
            continue
        if parsed.get("kind") != "confirmation":
            continue
        if parsed.get("status") == "decided":
            return parsed.get("decided")
    return None


def _parse_confirmation(
    requirement: RunRequirement,
    message_blocks: List[Dict[str, Any]],
) -> ParsedDecision:
    req_id = requirement.id or ""
    decided = _decided_from_blocks(message_blocks, req_id)
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
        approved=(decided == "approve"),
    )


def _parse_user_input(
    requirement: RunRequirement,
    state_values: Dict[str, Dict[str, Any]],
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    row_prefix = row_block_id(req_id, "user_input")
    values: Dict[str, Any] = {}

    for ui_field in requirement.user_input_schema or []:
        name = ui_field.name
        field_block_id = f"{row_prefix}:{name}"
        state_row = state_values.get(field_block_id) or {}
        action_id = f"{ACTION_INPUT_FIELD_PREFIX}{name}"
        action_state = state_row.get(action_id) or {}
        element_type = action_state.get("type")
        try:
            if element_type == "static_select":
                selected = action_state.get("selected_option") or {}
                raw = selected.get("value")
                values[name] = _coerce_input_value(raw, ui_field.field_type)
            else:
                raw = action_state.get("value")
                values[name] = _coerce_input_value(raw, ui_field.field_type)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(ParseError(requirement_id=req_id, field=name, message=str(exc)))
            values[name] = None

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="user_input",
        input_values=values,
    )


def _parse_user_feedback(
    requirement: RunRequirement,
    state_values: Dict[str, Dict[str, Any]],
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    base_row_bid = row_block_id(req_id, "user_feedback")
    selections: Dict[str, List[str]] = {}

    schema = requirement.user_feedback_schema or []
    for q_index, question in enumerate(schema):
        q_bid = f"{base_row_bid}:q{q_index}"
        state_q = state_values.get(q_bid) or {}
        action_state = state_q.get(f"{ACTION_FEEDBACK_SELECT}:{q_index}") or {}
        element_type = action_state.get("type")
        q_text = question.question

        picked: List[str] = []
        if element_type == "checkboxes":
            for opt in action_state.get("selected_options") or []:
                val = opt.get("value")
                if val:
                    picked.append(val)
        elif element_type == "static_select":
            opt = action_state.get("selected_option") or {}
            val = opt.get("value")
            if val:
                picked.append(val)

        if not picked:
            errors.append(ParseError(requirement_id=req_id, field=q_text, message="No option selected"))
        selections[q_text] = picked

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="user_feedback",
        feedback_selections=selections,
    )


def _parse_external(
    requirement: RunRequirement,
    state_values: Dict[str, Dict[str, Any]],
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    result_bid = f"{row_block_id(req_id, 'external_execution')}:result"
    state_row = state_values.get(result_bid) or {}
    action_state = state_row.get(ACTION_EXTERNAL_RESULT) or {}
    raw = (action_state.get("value") or "").strip()
    if not raw:
        errors.append(ParseError(requirement_id=req_id, field="result", message="Result must be non-empty"))
    return ParsedDecision(
        requirement_id=req_id,
        pause_type="external_execution",
        external_result=raw or None,
    )


def parse_submit_payload(
    payload: Dict[str, Any],
    requirements: List[RunRequirement],
    classify_fn: Optional[Callable[[RunRequirement], PauseType]] = None,
) -> tuple[List[ParsedDecision], List[ParseError]]:
    from agno.os.interfaces.slack.builders import classify_requirement

    if classify_fn is None:
        classify_fn = classify_requirement
    message_blocks: List[Dict[str, Any]] = (payload.get("message") or {}).get("blocks") or []
    state_values: Dict[str, Dict[str, Any]] = (payload.get("state") or {}).get("values") or {}

    decisions: List[ParsedDecision] = []
    errors: List[ParseError] = []

    for requirement in requirements:
        kind = classify_fn(requirement)
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
    by_id = {r.id: r for r in requirements if r.id}
    for decision in decisions:
        req = by_id.get(decision.requirement_id)
        if req is None:
            continue
        if decision.pause_type == "confirmation":
            if decision.approved:
                req.confirm()
            else:
                req.reject(decision.rejected_note)
        elif decision.pause_type == "user_input":
            if decision.input_values is not None:
                req.provide_user_input(decision.input_values)
        elif decision.pause_type == "user_feedback":
            if decision.feedback_selections is not None:
                req.provide_user_feedback(decision.feedback_selections)
        elif decision.pause_type == "external_execution":
            if decision.external_result:
                req.set_external_execution_result(decision.external_result)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _render_value(value: Any) -> str:
    try:
        rendered = value if isinstance(value, str) else json.dumps(value, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    if len(rendered) > DECISION_VALUE_MAX:
        rendered = rendered[: DECISION_VALUE_MAX - 1] + "…"
    return rendered


def _inline_args(args: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key, value in (args or {}).items():
        rendered = _render_value(value).replace("\n", " ").strip()
        parts.append(f"{key}={rendered}")
    return ", ".join(parts)


def _tool_name(requirement: RunRequirement) -> str:
    tool = requirement.tool_execution
    return getattr(tool, "tool_name", None) or "tool"


def _tool_args(requirement: RunRequirement) -> Dict[str, Any]:
    tool = requirement.tool_execution
    return getattr(tool, "tool_args", None) or {}


def format_decision_title(decision: ParsedDecision, requirement: RunRequirement) -> str:
    name = _tool_name(requirement)
    kind = decision.pause_type
    if kind == "confirmation":
        verb = "Approved" if decision.approved else "Denied"
        inline = _inline_args(_tool_args(requirement))
    elif kind == "user_input":
        verb = "Submitted"
        inline = _inline_args(decision.input_values or {})
    elif kind == "user_feedback":
        verb = "Submitted"
        flattened: Dict[str, Any] = {
            q: (picks[0] if len(picks) == 1 else picks) for q, picks in (decision.feedback_selections or {}).items()
        }
        inline = _inline_args(flattened)
    elif kind == "external_execution":
        verb = "Submitted"
        combined: Dict[str, Any] = dict(_tool_args(requirement))
        if decision.external_result is not None:
            combined["result"] = decision.external_result
        inline = _inline_args(combined)
    else:
        verb = "Submitted"
        inline = ""

    base = f"{verb}: {name}"
    title = f"{base}({inline})" if inline else base
    return _truncate(title, DECISION_TITLE_MAX)
