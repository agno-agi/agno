from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from agno.os.interfaces.slack.block_kit import (
    MAX_MESSAGE_BLOCKS,
    MAX_SECTION_FIELDS,
    Actions,
    Button,
    Checkboxes,
    ConfirmDialog,
    Context,
    Divider,
    InputBlock,
    Markdown,
    Option,
    PlainText,
    PlainTextInput,
    RichText,
    RichTextPlain,
    RichTextSection,
    Section,
    StaticSelect,
    TaskCard,
)
from agno.run.requirement import RunRequirement

# ---------------------------------------------------------------------------
# Protocol — block_id / action_id contract
#
# block_id format: row:<req_id>:<kind>:pending[:decided:<approve|reject>]
# Example: row:7f3a:confirmation:pending              (unresolved row)
#          row:7f3a:confirmation:decided:approve       (confirmation clicked)
#
# Parser uses bounded split(":", 4) so req_ids containing ":" stay intact
# through the first 3 segments.
# ---------------------------------------------------------------------------

PauseType = Literal["confirmation", "user_input", "user_feedback", "external_execution"]

ROW_BLOCK_PREFIX = "row"
PAUSE_BLOCK_PREFIX = "pause"

# Action IDs — closed set. parse_submit_payload (F5) rejects unknown values.
ACTION_SUBMIT = "submit_pause"
ACTION_ROW_APPROVE = "row_approve"
ACTION_ROW_REJECT = "row_reject"
ACTION_FEEDBACK_SELECT = "feedback_select"
ACTION_EXTERNAL_RESULT = "external_result"
# User-input field action_ids are namespaced per field: input_field:<field_name>
ACTION_INPUT_FIELD_PREFIX = "input_field:"

# Arg preview caps — keep messages scannable; full args still in logs.
_ARG_PREVIEW_MAX = 400
_ARG_VALUE_MAX = 120


# ---------------------------------------------------------------------------
# Parsed decision shapes
# ---------------------------------------------------------------------------


@dataclass
class ParsedDecision:
    requirement_id: str
    pause_type: PauseType
    # Only the field matching pause_type is populated — others stay None.
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


# ---------------------------------------------------------------------------
# Classification — matches os.agno.com DynamicHITLComponent getToolType order
# ---------------------------------------------------------------------------


def _classify_flags(
    *,
    user_feedback_schema: Any,
    requires_user_input: bool,
    external_execution_required: bool,
) -> PauseType:
    # Order mirrors os.agno.com utils.ts: feedback → external → user_input → confirmation
    if user_feedback_schema:
        return "user_feedback"
    if external_execution_required:
        return "external_execution"
    if requires_user_input:
        return "user_input"
    return "confirmation"


def classify_tool_execution(tool_execution: Optional[Dict[str, Any]]) -> PauseType:
    """Classify a serialized tool_execution dict. Fallback to confirmation if
    the DB round-trip dropped the tool_execution entirely."""
    if not tool_execution:
        return "confirmation"
    return _classify_flags(
        user_feedback_schema=tool_execution.get("user_feedback_schema"),
        requires_user_input=bool(tool_execution.get("requires_user_input")),
        external_execution_required=bool(tool_execution.get("external_execution_required")),
    )


def classify_requirement(requirement: RunRequirement) -> PauseType:
    """Classify a live RunRequirement by inspecting its tool_execution flags."""
    tool = requirement.tool_execution
    if tool is None:
        return "confirmation"
    return _classify_flags(
        user_feedback_schema=getattr(tool, "user_feedback_schema", None),
        requires_user_input=bool(getattr(tool, "requires_user_input", False)),
        external_execution_required=bool(getattr(tool, "external_execution_required", False)),
    )


# ---------------------------------------------------------------------------
# block_id / action_id helpers
# ---------------------------------------------------------------------------


def row_block_id(requirement_id: str, kind: PauseType, *, decided: Optional[str] = None) -> str:
    """Build a row block_id. decided is 'approve' or 'reject' when a
    confirmation row has been clicked."""
    base = f"{ROW_BLOCK_PREFIX}:{requirement_id}:{kind}:pending"
    if decided is None:
        return base
    return f"{ROW_BLOCK_PREFIX}:{requirement_id}:{kind}:decided:{decided}"


def parse_row_block_id(block_id: str) -> Optional[Dict[str, str]]:
    """Inverse of row_block_id. Returns dict with req_id/kind/status/decided
    or None if not a row block_id.

    Bounded split(":", 4) so a req_id containing ":" can't corrupt the parse
    (only the first 3 separators matter)."""
    if not block_id.startswith(f"{ROW_BLOCK_PREFIX}:"):
        return None
    parts = block_id.split(":", 4)
    # parts: [row, req_id, kind, status, maybe decided]
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
    """block_id for the SUBMIT actions block — lets the submit handler recover
    the approval_id without hunting through message metadata."""
    return f"{PAUSE_BLOCK_PREFIX}:{approval_id}"


# ---------------------------------------------------------------------------
# Arg value rendering — used by the 2-column Section(fields=...) grid
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def render_arg_value(value: Any) -> str:
    """Render a single tool arg value for Slack mrkdwn display."""
    try:
        rendered = value if isinstance(value, str) else json.dumps(value, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return _truncate(rendered, _ARG_VALUE_MAX)


# ---------------------------------------------------------------------------
# Row builders — one per pause type. Each returns list[Block].
# ---------------------------------------------------------------------------


def _build_arg_fields(args: Optional[Dict[str, Any]]) -> List[Markdown]:
    """Render tool args as a 2-column mrkdwn grid for Section(fields=...).

    Matches the user's Block Kit Builder reference pattern:
      *key:*
      value
    Capped at MAX_SECTION_FIELDS (Slack limit=10) with a byte budget so long
    values don't blow up the card.
    """
    if not args:
        return []
    fields: List[Markdown] = []
    total_chars = 0
    for key, value in args.items():
        if len(fields) >= MAX_SECTION_FIELDS - 1:
            # Reserve last slot for "… N more" overflow marker.
            remaining = len(args) - len(fields)
            if remaining > 0:
                fields.append(Markdown(text=f"_… {remaining} more_"))
            break
        rendered = f"*{key}:*\n{render_arg_value(value)}"
        if total_chars + len(rendered) > _ARG_PREVIEW_MAX:
            remaining = len(args) - len(fields)
            fields.append(Markdown(text=f"_… {remaining} more_"))
            break
        fields.append(Markdown(text=rendered))
        total_chars += len(rendered)
    return fields


def _tool_name(requirement: RunRequirement) -> str:
    tool = requirement.tool_execution
    return getattr(tool, "tool_name", None) or "tool"


def _tool_args(requirement: RunRequirement) -> Dict[str, Any]:
    tool = requirement.tool_execution
    return getattr(tool, "tool_args", None) or {}


def _confirmation_buttons(button_value: str, approve_confirm, deny_confirm) -> List[Button]:
    """Approve / Deny buttons carrying the req_id|approval_id routing key."""
    return [
        Button(
            action_id=ACTION_ROW_APPROVE,
            text=PlainText(text="Approve", emoji=True),
            style="primary",
            value=button_value,
            confirm=approve_confirm,
        ),
        Button(
            action_id=ACTION_ROW_REJECT,
            text=PlainText(text="Deny", emoji=True),
            style="danger",
            value=button_value,
            confirm=deny_confirm,
        ),
    ]


def _build_confirm_dialogs(tool_name: str, args: Dict[str, Any]):
    """Native Slack confirm-dialog modals for Approve/Deny clicks.
    Slack caps dialog text at 300 chars, title at 100."""
    bullets: List[str] = []
    running = 0
    for key, value in (args or {}).items():
        line = f"• {key}: `{render_arg_value(value)}`"
        if running + len(line) > 180:
            bullets.append(f"_… {len(args) - len(bullets)} more_")
            break
        bullets.append(line)
        running += len(line)
    args_block = "\n".join(bullets) if bullets else "_(no arguments)_"
    approve_text = (f"{args_block}\n\n_Approving will resume the agent run._")[:299]
    deny_text = (f"{args_block}\n\n_The agent will continue without running this tool._")[:299]
    approve = ConfirmDialog(
        title=PlainText(text=f"Approve {tool_name}?"[:100]),
        text=Markdown(text=approve_text),
        confirm=PlainText(text="Yes, approve"),
        deny=PlainText(text="Cancel"),
        style="primary",
    )
    deny = ConfirmDialog(
        title=PlainText(text=f"Deny {tool_name}?"[:100]),
        text=Markdown(text=deny_text),
        confirm=PlainText(text="Yes, deny"),
        deny=PlainText(text="Cancel"),
        style="danger",
    )
    return approve, deny


def _args_as_rich_text(args: Optional[Dict[str, Any]]) -> Optional[RichText]:
    """Render tool args as rich_text sections (one per arg). Used in
    TaskCard.details — uses bold for keys and plain text for values.
    `code` style on rich_text elements appears to be silently dropped by
    Slack's task_card rendering, so we avoid it here."""
    if not args:
        return None
    sections: List[RichTextSection] = []
    for key, value in args.items():
        sections.append(
            RichTextSection(
                elements=[
                    RichTextPlain(text=f"{key}: ", style={"bold": True}),
                    RichTextPlain(text=render_arg_value(value)),
                ]
            )
        )
    return RichText(elements=sections)


def _approval_task_id(req_id: str) -> str:
    """Namespaced task_id for HITL task cards so they can\'t collide with
    streaming tool-call task cards."""
    return f"approval:{req_id}"


def _build_confirmation_row(requirement: RunRequirement, approval_id: str = "") -> List[Any]:
    """Confirmation row — TaskCard(pending) + Actions(Approve, Deny).

    Uses Slack\'s native task_card block so the approval matches the visual
    language of the streamed tool-call task cards above it. The Actions
    block carries its own block_id so _handle_row_click can route the click
    via button_value (req_id|approval_id).
    """
    req_id = requirement.id or ""
    tool_name = _tool_name(requirement)
    args = _tool_args(requirement)
    approve_confirm, deny_confirm = _build_confirm_dialogs(tool_name, args)
    return [
        TaskCard(
            block_id=row_block_id(req_id, "confirmation"),
            task_id=_approval_task_id(req_id),
            title=f"Approval required: {tool_name}",
            status="in_progress",
            details=_args_as_rich_text(args),
        ),
        Actions(
            block_id=f"rowact:{req_id}:confirmation",
            elements=_confirmation_buttons(f"{req_id}|{approval_id}", approve_confirm, deny_confirm),
        ),
    ]


# Mapping of Python UserInputField.field_type → Slack input element.
# int/float use plain_text_input (Slack has no numeric input); we parse at submit.
# bool uses a StaticSelect with True/False options.
# list/dict use multiline plain_text_input (user pastes JSON); we parse at submit.
_BOOL_OPTIONS = [
    Option(text=PlainText(text="True"), value="true"),
    Option(text=PlainText(text="False"), value="false"),
]


def _build_input_field(req_id: str, ui_field: Any) -> InputBlock:
    """Turn a UserInputField into a Slack InputBlock."""
    name = getattr(ui_field, "name", "field")
    description = getattr(ui_field, "description", None)
    field_type = getattr(ui_field, "field_type", str)
    initial_raw = getattr(ui_field, "value", None)

    type_name = field_type.__name__ if isinstance(field_type, type) else str(field_type)

    if type_name == "bool":
        element: Any = StaticSelect(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainText(text="Select"),
            options=_BOOL_OPTIONS,
        )
    else:
        multiline = type_name in ("list", "dict")
        initial_value: Optional[str] = None
        if initial_raw is not None:
            initial_value = initial_raw if isinstance(initial_raw, str) else json.dumps(initial_raw, default=str)
        element = PlainTextInput(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainText(text=f"Enter {name}"),
            initial_value=initial_value,
            multiline=multiline if multiline else None,
        )

    return InputBlock(
        # Namespace per field — Slack rejects duplicate block_ids. Previously
        # every field shared row_block_id(..., "user_input"); now we append
        # the field name so each InputBlock has a unique id.
        block_id=f"{row_block_id(req_id, 'user_input')}:{name}",
        label=PlainText(text=name),
        element=element,
        hint=PlainText(text=description) if description else None,
    )


def _build_input_row(requirement: RunRequirement) -> List[Any]:
    """user_input row — TaskCard(pending) + one InputBlock per schema field.

    TaskCard header signals the pause and keeps visual parity with the
    streamed tool-call task cards. Each user_input_schema field becomes its
    own InputBlock with a Slack input element chosen by field_type.
    """
    req_id = requirement.id or ""
    tool_name = _tool_name(requirement)
    blocks: List[Any] = [
        TaskCard(
            block_id=row_block_id(req_id, "user_input"),
            task_id=_approval_task_id(req_id),
            title=f"Input required: {tool_name}",
            status="in_progress",
            details=_args_as_rich_text(_tool_args(requirement)),
        ),
    ]
    schema = requirement.user_input_schema or []
    for ui_field in schema:
        blocks.append(_build_input_field(req_id, ui_field))
    return blocks


# ---------------------------------------------------------------------------
# user_feedback — one card per question. Multi-select → Checkboxes,
# single-select → StaticSelect (Slack SDK 3.41 lacks RadioButtons).
# ---------------------------------------------------------------------------


def _option_to_slack(option: Any, index: int) -> Option:
    """Convert a UserFeedbackOption to a Block Kit Option. The option.label is
    used as BOTH the display text AND the value — that's how we recover the
    selected labels at SUBMIT time to pass back to provide_user_feedback()."""
    label = getattr(option, "label", f"option-{index}")
    description = getattr(option, "description", None)
    return Option(
        text=PlainText(text=label),
        value=label,
        description=PlainText(text=description) if description else None,
    )


def _build_feedback_question(req_id: str, question: Any, q_index: int) -> InputBlock:
    """One InputBlock per UserFeedbackQuestion."""
    prompt = getattr(question, "question", f"Question {q_index + 1}")
    options = getattr(question, "options", None) or []
    multi_select = bool(getattr(question, "multi_select", False))

    slack_options = [_option_to_slack(opt, i) for i, opt in enumerate(options)]

    element: Any
    if multi_select:
        # Checkboxes — matches os.agno.com "full-width checkbox option card" UX.
        element = Checkboxes(
            action_id=f"{ACTION_FEEDBACK_SELECT}:{q_index}",
            options=slack_options,
        )
    else:
        element = StaticSelect(
            action_id=f"{ACTION_FEEDBACK_SELECT}:{q_index}",
            placeholder=PlainText(text="Select one"),
            options=slack_options,
        )

    return InputBlock(
        # Block ID carries question index so the parser knows which schema
        # entry a selection belongs to.
        block_id=f"{row_block_id(req_id, 'user_feedback')}:q{q_index}",
        label=PlainText(text=prompt),
        element=element,
    )


def _build_feedback_row(requirement: RunRequirement) -> List[Any]:
    """user_feedback row — TaskCard(pending) + one question input per schema entry."""
    req_id = requirement.id or ""
    tool_name = _tool_name(requirement)
    blocks: List[Any] = [
        TaskCard(
            block_id=row_block_id(req_id, "user_feedback"),
            task_id=_approval_task_id(req_id),
            title=f"Feedback needed: {tool_name}",
            status="in_progress",
        ),
    ]
    schema = requirement.user_feedback_schema or []
    for i, question in enumerate(schema):
        blocks.append(_build_feedback_question(req_id, question, i))
    return blocks


# ---------------------------------------------------------------------------
# external_execution — single multiline input for the result string.
# Framework requires non-empty; we hint that at submit parse time (F5).
# ---------------------------------------------------------------------------


def _build_external_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    tool_name = _tool_name(requirement)
    return [
        TaskCard(
            block_id=row_block_id(req_id, "external_execution"),
            task_id=_approval_task_id(req_id),
            title=f"Output required: {tool_name}",
            status="in_progress",
            details=_args_as_rich_text(_tool_args(requirement)),
        ),
        InputBlock(
            block_id=f"{row_block_id(req_id, 'external_execution')}:result",
            label=PlainText(text="Result"),
            element=PlainTextInput(
                action_id=ACTION_EXTERNAL_RESULT,
                placeholder=PlainText(text="Paste the execution output here"),
                multiline=True,
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Dispatch + assembly
# ---------------------------------------------------------------------------


_BUILDERS = {
    "confirmation": _build_confirmation_row,
    "user_input": _build_input_row,
    "user_feedback": _build_feedback_row,
    "external_execution": _build_external_row,
}


def _submit_actions_block(approval_id: str) -> Actions:
    """Global SUBMIT button, rendered only when the pause has rows that
    collect form state (user_input / user_feedback / external_execution).
    Confirmation-only pauses use atomic Approve/Deny-with-confirm buttons
    and skip the Submit entirely."""
    return Actions(
        block_id=pause_block_id(approval_id),
        elements=[
            Button(
                action_id=ACTION_SUBMIT,
                text=PlainText(text="Submit"),
                style="primary",
                value=approval_id,
            ),
        ],
    )


def _resolved_row_block(
    requirement: RunRequirement, decision: Literal["approve", "reject"], note: Optional[str] = None
) -> Section:
    """Replacement block rendered after a confirmation row is decided. Shows
    a decided chip instead of Approve/Deny buttons."""
    req_id = requirement.id or ""
    chip = "✅ Approved" if decision == "approve" else f"❌ Rejected{': ' + note if note else ''}"
    return Section(
        block_id=row_block_id(req_id, "confirmation", decided=decision),
        text=Markdown(text=f"*{_tool_name(requirement)}* — {chip}"),
    )


def build_pause_message(
    approval_id: str,
    requirements: List[RunRequirement],
) -> List[Any]:
    """Assemble the full pause message: rows + optional truncation notice + SUBMIT.

    Slack caps messages at 50 blocks; we target MAX_MESSAGE_BLOCKS=48 so the
    final SUBMIT + an optional overflow context block fit under the cap. If the
    requirement set would exceed that, we truncate and post a Context note
    explaining how many were omitted — remaining ones can re-render after
    SUBMIT resolves the shown batch.
    """
    blocks: List[Any] = []
    processed = 0
    truncated_count = 0
    total = len(requirements)
    budget = MAX_MESSAGE_BLOCKS - 2  # reserve SUBMIT + overflow context

    for i, requirement in enumerate(requirements):
        kind = classify_requirement(requirement)
        # Confirmation builder gets approval_id so Approve/Deny buttons can
        # carry it in their `value` field (avoiding dependence on a Submit
        # block that we drop for confirmation-only pauses).
        if kind == "confirmation":
            row_blocks = _build_confirmation_row(requirement, approval_id=approval_id)
        else:
            row_blocks = _BUILDERS[kind](requirement)
        # Divider between rows (skip before the first).
        header_size = 1 if i > 0 else 0
        if len(blocks) + header_size + len(row_blocks) > budget:
            truncated_count = total - processed
            break
        if i > 0:
            blocks.append(Divider())
        blocks.extend(row_blocks)
        processed += 1

    if truncated_count:
        blocks.append(
            Context(
                elements=[
                    Markdown(
                        text=f":warning: _{truncated_count} more pause row(s) omitted — "
                        "Slack message cap. Resolve the shown rows; remaining re-render after submit._"
                    )
                ],
            )
        )

    # Submit is ONLY rendered when at least one row collects form state
    # (user_input / user_feedback / external_execution). For confirmation-
    # only pauses, each card's Approve/Deny buttons carry their own native
    # confirm-dialog and are atomic — no separate Submit click needed.
    needs_submit = any(classify_requirement(r) != "confirmation" for r in requirements[:processed])
    if needs_submit:
        blocks.append(_submit_actions_block(approval_id))
    return blocks


# ---------------------------------------------------------------------------
# SUBMIT payload parser
# ---------------------------------------------------------------------------


def _coerce_input_value(raw: Optional[str], field_type: Any) -> Any:
    """Turn a Slack-submitted string into the declared Python type. Raises
    ValueError on bad input — caller converts to ParseError."""
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
    """Scan message.blocks (as dicts from the inbound Slack payload) for a
    confirmation row in decided state. Returns 'approve' / 'reject' or None."""
    for block in message_blocks:
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
        # No click registered — treat as rejected by default to keep runs safe.
        # (user can re-submit with explicit Approve to move forward.)
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
    # Each field's InputBlock has a per-field block_id (row:<req>:user_input:pending:<name>)
    # so state_values is keyed by that unique id.
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
                # bool fields come through static_select with "true"/"false" values
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
) -> tuple[List[ParsedDecision], List[ParseError]]:
    """Consume a Slack block_actions payload from a SUBMIT click and produce
    one ParsedDecision per requirement plus a list of ParseErrors."""
    message_blocks: List[Dict[str, Any]] = (payload.get("message") or {}).get("blocks") or []
    state_values: Dict[str, Dict[str, Any]] = (payload.get("state") or {}).get("values") or {}

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


# ---------------------------------------------------------------------------
# Dispatch — apply ParsedDecisions onto RunRequirement instances so they're
# ready for agent.acontinue_run(requirements=[...]).
# ---------------------------------------------------------------------------


def apply_decisions(
    decisions: List[ParsedDecision],
    requirements: List[RunRequirement],
) -> None:
    """Mutate each RunRequirement in place with the matching ParsedDecision.
    Caller must supply hydrated RunRequirement objects (via from_dict if
    they came out of the approval row)."""
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
