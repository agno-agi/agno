from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, get_args

from slack_sdk.models.blocks import (
    ActionsBlock,
    CheckboxesElement,
    ContextBlock,
    DividerBlock,
    InputBlock,
    PlainTextInputElement,
    StaticSelectElement,
)
from slack_sdk.models.blocks.basic_components import MarkdownTextObject, Option, PlainTextObject
from slack_sdk.models.blocks.block_elements import ButtonElement

from agno.os.interfaces.slack.components import Card
from agno.os.interfaces.slack.ids import (
    ACTION_EXTERNAL_RESULT,
    ACTION_REJECT_REASON,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    ACTION_SUBMIT,
    encode_row_button_value,
    encode_submit_button_value,
    external_result_block_id,
    feedback_action_id,
    pause_block_id,
    user_feedback_block_id,
    user_input_action_id,
    user_input_block_id,
)
from agno.os.interfaces.slack.types import (
    RowActionContext,
    RowTransformResult,
    block_to_dict,
    tool_args,
    tool_name,
)
from agno.run.requirement import RunRequirement
from agno.utils.serialize import json_serializer

# Slack caps messages at 50 blocks
MAX_MESSAGE_BLOCKS = 50


# Formats tool arg values for display in HITL approval cards; strings pass through, others JSON-encode
def render_arg_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=json_serializer)
    except (TypeError, ValueError):
        return str(value)


# --- Type detection helpers ---


def _is_literal(field_type: Any) -> bool:
    return str(field_type).startswith("typing.Literal")


def _is_enum(field_type: Any) -> bool:
    return isinstance(field_type, type) and issubclass(field_type, Enum)


def _is_bool(field_type: Any) -> bool:
    return field_type is bool or (isinstance(field_type, type) and field_type.__name__ == "bool")


# --- Element builders ---


def _build_select_element(name: str, options: List[Tuple[str, str]]) -> StaticSelectElement:
    return StaticSelectElement(
        action_id=user_input_action_id(name),
        placeholder=PlainTextObject(text="Select"),
        options=[Option(text=PlainTextObject(text=text), value=value) for text, value in options],
    )


def _build_text_input(name: str, field_type: Any, initial_raw: Any) -> PlainTextInputElement:
    type_name = field_type.__name__ if isinstance(field_type, type) else str(field_type)
    multiline = type_name in ("list", "dict")
    initial_value: Optional[str] = None
    if initial_raw is not None:
        initial_value = initial_raw if isinstance(initial_raw, str) else json.dumps(initial_raw, default=str)
    return PlainTextInputElement(
        action_id=user_input_action_id(name),
        placeholder=PlainTextObject(text=f"Enter {name}"),
        initial_value=initial_value,
        multiline=multiline or None,
    )


# Maps Python type → Slack input element: dropdown for finite choices (Literal/Enum/bool), text box otherwise
def _field_type_to_input_element(name: str, field_type: Any, initial_raw: Any) -> Any:
    # Literal["a", "b"] → dropdown
    if _is_literal(field_type):
        args = get_args(field_type)
        return _build_select_element(name, [(str(a), str(a)) for a in args])

    # Enum → dropdown
    if _is_enum(field_type):
        return _build_select_element(name, [(m.name, m.name) for m in field_type])

    # bool → dropdown (True/False)
    if _is_bool(field_type):
        return _build_select_element(name, [("True", "true"), ("False", "false")])

    # Everything else → text input
    return _build_text_input(name, field_type, initial_raw)


# --- Main builder ---


# Converts a Pydantic field schema into a Slack Block Kit input element for HITL user_input cards
def _build_input_field(req_id: str, ui_field: Any) -> InputBlock:
    name = getattr(ui_field, "name", "field")
    description = getattr(ui_field, "description", None)
    field_type = getattr(ui_field, "field_type", str)
    initial_raw = getattr(ui_field, "value", None)

    element = _field_type_to_input_element(name, field_type, initial_raw)

    return InputBlock(
        block_id=user_input_block_id(req_id, name),
        label=PlainTextObject(text=name),
        element=element,
        hint=PlainTextObject(text=description) if description else None,
    )


def _user_feedback_option_to_slack_option(option: Any, index: int) -> Option:
    label = getattr(option, "label", f"option-{index}")
    description = getattr(option, "description", None)
    return Option(
        text=PlainTextObject(text=label),
        value=label,
        description=PlainTextObject(text=description) if description else None,
    )


# Checkboxes if multi_select, dropdown otherwise
def _feedback_question_to_input_element(slack_options: List[Option], multi_select: bool, q_index: int) -> Any:
    if multi_select:
        return CheckboxesElement(
            action_id=feedback_action_id(q_index),
            options=slack_options,
        )
    return StaticSelectElement(
        action_id=feedback_action_id(q_index),
        placeholder=PlainTextObject(text="Select one"),
        options=slack_options,
    )


# Builds Slack InputBlock for a HITL user_feedback question
def _build_user_feedback_question_block(req_id: str, question: Any, q_index: int) -> InputBlock:
    prompt = getattr(question, "question", f"Question {q_index + 1}")
    options = getattr(question, "options", None) or []
    multi_select = bool(getattr(question, "multi_select", False))

    slack_options = [_user_feedback_option_to_slack_option(opt, i) for i, opt in enumerate(options)]
    element = _feedback_question_to_input_element(slack_options, multi_select, q_index)

    return InputBlock(
        block_id=user_feedback_block_id(req_id, q_index),
        label=PlainTextObject(text=prompt),
        element=element,
    )


# Builds HITL confirmation card with Approve/Deny buttons for a tool execution
def _build_confirmation_card(requirement: RunRequirement, run_id: str = "", awaiting_ts: Optional[str] = None) -> Card:
    req_id = requirement.id or ""
    name = tool_name(requirement)
    args = tool_args(requirement)
    button_value = encode_row_button_value(req_id, run_id, awaiting_ts)
    # Format args as bullet points in body (not subtitle which truncates)
    body_lines = [f"• {k}: `{render_arg_value(v)}`" for k, v in (args or {}).items()]
    body_text = "\n".join(body_lines) if body_lines else "_(no arguments)_"
    return Card(
        block_id=f"rowact:{req_id}:confirmation",
        title=MarkdownTextObject(text=f"*{name}*"),
        body=MarkdownTextObject(text=body_text),
        actions=[
            ButtonElement(
                action_id=ACTION_ROW_APPROVE,
                text=PlainTextObject(text="Approve", emoji=True),
                style="primary",
                value=button_value,
            ),
            ButtonElement(
                action_id=ACTION_ROW_REJECT,
                text=PlainTextObject(text="Deny", emoji=True),
                style="danger",
                value=button_value,
            ),
        ],
    )


# Confirmation card with toggle state — selected button gets styled + past tense label
def build_confirmation_toggle_card(
    req_id: str,
    run_id: str,
    awaiting_ts: Optional[str],
    tool_name: str,
    body_text: str,
    selected: str,
) -> Card:
    button_value = encode_row_button_value(req_id, run_id, awaiting_ts)
    is_approved = selected == "approve"

    approve_btn = ButtonElement(
        action_id=ACTION_ROW_APPROVE,
        text=PlainTextObject(text="Approved" if is_approved else "Approve", emoji=True),
        style="primary" if is_approved else None,
        value=button_value,
    )
    deny_btn = ButtonElement(
        action_id=ACTION_ROW_REJECT,
        text=PlainTextObject(text="Denied" if not is_approved else "Deny", emoji=True),
        style="danger" if not is_approved else None,
        value=button_value,
    )

    return Card(
        block_id=f"rowact:{req_id}:confirmation:selected:{selected}",
        title=MarkdownTextObject(text=f"*{tool_name}*"),
        body=MarkdownTextObject(text=body_text),
        actions=[approve_btn, deny_btn],
    )


# --- Row transformation helpers ---


def decision_marker(req_id: str, decision: str) -> Dict[str, Any]:
    return {
        "type": "section",
        "block_id": f"row:{req_id}:confirmation:decided:{decision}",
        "text": {"type": "plain_text", "text": " "},
    }


def build_submit_button(run_id: str, awaiting_ts: Optional[str]) -> Dict[str, Any]:
    submit_btn = ButtonElement(
        action_id="submit_pause",
        text=PlainTextObject(text="Submit", emoji=True),
        style="primary",
        value=encode_submit_button_value(run_id, awaiting_ts),
    )
    return ActionsBlock(block_id=f"pause:{run_id}", elements=[submit_btn]).to_dict()


def select_confirmation_row(
    ctx: RowActionContext,
    selected: str,
    include_reason_input: bool = False,
) -> RowTransformResult:
    from agno.os.interfaces.slack.interactions import confirmation_row_summary

    updated: List[Dict[str, Any]] = []
    for block in ctx.blocks:
        block_id = block.get("block_id", "")

        # Clicked row — replace with toggle card
        if block_id.startswith(f"rowact:{ctx.req_id}:confirmation"):
            name = (block.get("title") or {}).get("text", "*tool*").replace("*", "")
            body_text = (block.get("body") or {}).get("text", "")
            toggle_card = build_confirmation_toggle_card(
                req_id=ctx.req_id,
                run_id=ctx.run_id,
                awaiting_ts=ctx.awaiting_ts,
                tool_name=name,
                body_text=body_text,
                selected=selected,
            )
            updated.append(block_to_dict(toggle_card))
            # Deny keeps card interactive so user can add optional reason before Submit
            if include_reason_input:
                reason_input = InputBlock(
                    block_id=f"reject_reason:{ctx.req_id}",
                    label=PlainTextObject(text="Reason (optional)"),
                    element=PlainTextInputElement(
                        action_id=ACTION_REJECT_REASON,
                        placeholder=PlainTextObject(text="Why are you rejecting this action?"),
                        multiline=True,
                    ),
                    optional=True,
                )
                updated.append(block_to_dict(reason_input))
            updated.append(decision_marker(ctx.req_id, selected))
            continue

        # Skip stale decision markers and reason inputs for this row
        if block_id.startswith(f"row:{ctx.req_id}:confirmation:decided:"):
            continue
        if block_id == f"reject_reason:{ctx.req_id}":
            continue

        # Preserve all other blocks
        updated.append(block)

    summary = confirmation_row_summary(updated)
    should_auto_submit = bool(ctx.run_id and not summary.pending_ids and not summary.has_global_submit)
    return RowTransformResult(blocks=updated, should_auto_submit=should_auto_submit)


def append_submit_if_needed(
    blocks: List[Dict[str, Any]],
    run_id: str,
    awaiting_ts: Optional[str],
) -> List[Dict[str, Any]]:
    from agno.os.interfaces.slack.interactions import confirmation_row_summary

    if not run_id:
        return blocks
    summary = confirmation_row_summary(blocks)
    if summary.pending_ids or summary.has_global_submit:
        return blocks
    return blocks + [build_submit_button(run_id, awaiting_ts)]


# Builds InputBlocks for user_input pause type (text fields, dropdowns for bool/Enum/Literal)
def _build_input_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    blocks: List[Any] = []
    schema = requirement.user_input_schema or []
    for ui_field in schema:
        blocks.append(_build_input_field(req_id, ui_field))
    return blocks


# Builds InputBlocks for user_feedback pause type (multiple-choice questions)
def _build_feedback_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    blocks: List[Any] = []
    schema = requirement.user_feedback_schema or []
    for i, question in enumerate(schema):
        blocks.append(_build_user_feedback_question_block(req_id, question, i))
    return blocks


# Builds InputBlock for external_execution pause type (paste execution result here)
def _build_external_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    return [
        InputBlock(
            block_id=external_result_block_id(req_id),
            label=PlainTextObject(text="Result"),
            element=PlainTextInputElement(
                action_id=ACTION_EXTERNAL_RESULT,
                placeholder=PlainTextObject(text="Paste the execution output here"),
                multiline=True,
            ),
        ),
    ]


def build_pause_message(
    run_id: str,
    requirements: List[RunRequirement],
    awaiting_ts: Optional[str] = None,
) -> List[Any]:
    blocks: List[Any] = []
    processed = 0
    truncated_count = 0
    total = len(requirements)
    # Reserve 2 blocks for Submit button + truncation warning
    budget = MAX_MESSAGE_BLOCKS - 2

    for i, requirement in enumerate(requirements):
        kind = requirement.pause_type
        if kind == "confirmation":
            row_blocks = [_build_confirmation_card(requirement, run_id=run_id, awaiting_ts=awaiting_ts)]
        else:
            # Input/feedback/external rows: just fields, global Submit handles submission
            if kind == "user_input":
                row_blocks = _build_input_row(requirement)
            elif kind == "user_feedback":
                row_blocks = _build_feedback_row(requirement)
            elif kind == "external_execution":
                row_blocks = _build_external_row(requirement)
            else:
                continue

        header_size = 1 if i > 0 else 0
        if len(blocks) + header_size + len(row_blocks) > budget:
            truncated_count = total - processed
            break
        if i > 0:
            blocks.append(DividerBlock())
        blocks.extend(row_blocks)
        processed += 1

    if truncated_count:
        blocks.append(
            ContextBlock(
                elements=[
                    MarkdownTextObject(
                        text=f":warning: _{truncated_count} more pause row(s) omitted — "
                        "Slack message cap. Resolve shown rows; remaining re-render after._"
                    )
                ],
            )
        )

    # Global Submit button for non-confirmation rows (input/feedback/external)
    needs_submit = any(r.pause_type != "confirmation" for r in requirements[:processed])
    if needs_submit:
        blocks.append(
            ActionsBlock(
                block_id=pause_block_id(run_id),
                elements=[
                    ButtonElement(
                        action_id=ACTION_SUBMIT,
                        text=PlainTextObject(text="Submit"),
                        style="primary",
                        value=encode_submit_button_value(run_id, awaiting_ts),
                    ),
                ],
            )
        )
    return blocks


# --- response_blocks helpers ---


def _should_skip_block(btype: str, block_id: str) -> bool:
    if btype == "actions":
        return True
    if btype == "section" and ":confirmation:decided:" in block_id:
        return True
    if block_id.startswith("reject_reason:"):
        return True
    return False


def _finalize_card(block: Dict[str, Any]) -> Dict[str, Any]:
    card = {k: v for k, v in block.items() if k != "actions"}
    block_id = block.get("block_id", "")
    title_text = (card.get("title") or {}).get("text", "")

    if ":selected:approve" in block_id:
        card["title"] = {"type": "mrkdwn", "text": f"*Approved:* {title_text.replace('*', '')}"}
    elif ":selected:deny" in block_id:
        card["title"] = {"type": "mrkdwn", "text": f"*Denied:* {title_text.replace('*', '')}"}

    return card


def _extract_input_value(element: Dict[str, Any], submitted: Dict[str, Any]) -> str:
    etype = element.get("type")

    if etype == "plain_text_input":
        return submitted.get("value") or "_(empty)_"

    if etype == "static_select":
        opt = submitted.get("selected_option") or {}
        return (opt.get("text") or {}).get("text") or opt.get("value") or "_(none)_"

    if etype in ("checkboxes", "multi_static_select"):
        opts = submitted.get("selected_options") or []
        labels = [((o.get("text") or {}).get("text") or o.get("value") or "") for o in opts]
        return ", ".join(labels) if labels else "_(none)_"

    return "_(submitted)_"


# Replaces interactive form with readonly summary so users see what was submitted
def response_blocks(
    original_blocks: List[Dict[str, Any]],
    state_values: Dict[str, Dict[str, Any]],
    requirements: List[RunRequirement],
) -> List[Dict[str, Any]]:
    preserved: List[Dict[str, Any]] = []
    submissions: List[str] = []

    for block in original_blocks:
        btype = block.get("type", "")
        block_id = block.get("block_id", "")

        if _should_skip_block(btype, block_id):
            continue

        if btype == "card":
            preserved.append(_finalize_card(block))
            continue

        if btype != "input":
            preserved.append(block)
            continue

        # Extract submitted value from input block
        label = (block.get("label") or {}).get("text", "")
        element = block.get("element") or {}
        action_id = element.get("action_id", "")
        submitted = (state_values.get(block_id) or {}).get(action_id) or {}
        value = _extract_input_value(element, submitted)
        submissions.append(f"• {label}: `{value}`")

    if not submissions:
        return preserved

    body_text = "\n".join(submissions)
    if len(body_text) > 200:
        body_text = body_text[:197] + "..."

    return preserved + [
        {
            "type": "card",
            "title": {"type": "mrkdwn", "text": "*Submitted*"},
            "body": {"type": "mrkdwn", "text": body_text},
        }
    ]
