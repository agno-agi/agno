from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, get_args

from slack_sdk.models.blocks import (
    CheckboxesElement,
    ContextBlock,
    DividerBlock,
    InputBlock,
    PlainTextInputElement,
    StaticSelectElement,
)
from slack_sdk.models.blocks.basic_components import MarkdownTextObject, Option, PlainTextObject
from slack_sdk.models.blocks.block_elements import ButtonElement, ImageElement

from agno.os.interfaces.slack.types import (
    ACTION_EXTERNAL_RESULT,
    ACTION_FEEDBACK_SELECT,
    ACTION_INPUT_FIELD_PREFIX,
    ACTION_REJECT_CANCEL,
    ACTION_REJECT_CONFIRM,
    ACTION_REJECT_REASON,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    _tool_args,
    _tool_name,
    encode_reject_card_value,
    encode_row_button_value,
    row_block_id,
)
from agno.run.requirement import RunRequirement
from agno.utils.serialize import json_serializer

# Slack caps messages at 50 blocks
MAX_MESSAGE_BLOCKS = 50


@dataclass
class Card:
    # Card block shipped in Slack API 2024 but slack_sdk lacks model class
    actions: List[ButtonElement]
    icon: Optional[ImageElement] = None
    title: Optional[PlainTextObject | MarkdownTextObject] = None
    subtitle: Optional[PlainTextObject | MarkdownTextObject] = None
    body: Optional[PlainTextObject | MarkdownTextObject] = None
    block_id: Optional[str] = None

    @property
    def type(self) -> str:
        return "card"

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": self.type,
            "actions": [a.to_dict() for a in self.actions],
        }
        if self.icon:
            result["icon"] = self.icon.to_dict()
        if self.title:
            result["title"] = self.title.to_dict()
        if self.subtitle:
            result["subtitle"] = self.subtitle.to_dict()
        if self.body:
            result["body"] = self.body.to_dict()
        if self.block_id:
            result["block_id"] = self.block_id
        return result


def render_arg_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=json_serializer)
    except (TypeError, ValueError):
        return str(value)


# Slack lacks native boolean input; checkbox implies multi-select which is confusing
_BOOL_OPTIONS = [
    Option(text=PlainTextObject(text="True"), value="true"),
    Option(text=PlainTextObject(text="False"), value="false"),
]


def _build_input_field(req_id: str, ui_field: Any) -> InputBlock:
    name = getattr(ui_field, "name", "field")
    description = getattr(ui_field, "description", None)
    field_type = getattr(ui_field, "field_type", str)
    initial_raw = getattr(ui_field, "value", None)

    type_name = field_type.__name__ if isinstance(field_type, type) else str(field_type)
    element: Any = None

    # Check for typing.Literal — renders as dropdown with literal values as options
    literal_args = get_args(field_type) if str(field_type).startswith("typing.Literal") else None
    if literal_args:
        options = [Option(text=PlainTextObject(text=str(arg)), value=str(arg)) for arg in literal_args]
        element = StaticSelectElement(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainTextObject(text="Select"),
            options=options,
        )

    # Check for Enum subclass — renders as dropdown with enum members as options
    elif isinstance(field_type, type) and issubclass(field_type, Enum):
        options = [Option(text=PlainTextObject(text=member.name), value=member.name) for member in field_type]
        element = StaticSelectElement(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainTextObject(text="Select"),
            options=options,
        )

    elif type_name == "bool":
        element = StaticSelectElement(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainTextObject(text="Select"),
            options=_BOOL_OPTIONS,
        )

    if element is None:
        multiline = type_name in ("list", "dict")
        initial_value: Optional[str] = None
        if initial_raw is not None:
            initial_value = initial_raw if isinstance(initial_raw, str) else json.dumps(initial_raw, default=str)
        element = PlainTextInputElement(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainTextObject(text=f"Enter {name}"),
            initial_value=initial_value,
            multiline=multiline or None,
        )

    return InputBlock(
        block_id=f"{row_block_id(req_id, 'user_input')}:{name}",
        label=PlainTextObject(text=name),
        element=element,
        hint=PlainTextObject(text=description) if description else None,
    )


def _option_to_slack(option: Any, index: int) -> Option:
    label = getattr(option, "label", f"option-{index}")
    description = getattr(option, "description", None)
    return Option(
        text=PlainTextObject(text=label),
        value=label,
        description=PlainTextObject(text=description) if description else None,
    )


def _build_feedback_question(req_id: str, question: Any, q_index: int) -> InputBlock:
    prompt = getattr(question, "question", f"Question {q_index + 1}")
    options = getattr(question, "options", None) or []
    multi_select = bool(getattr(question, "multi_select", False))

    slack_options = [_option_to_slack(opt, i) for i, opt in enumerate(options)]

    element: Any
    if multi_select:
        element = CheckboxesElement(
            action_id=f"{ACTION_FEEDBACK_SELECT}:{q_index}",
            options=slack_options,
        )
    else:
        element = StaticSelectElement(
            action_id=f"{ACTION_FEEDBACK_SELECT}:{q_index}",
            placeholder=PlainTextObject(text="Select one"),
            options=slack_options,
        )

    return InputBlock(
        block_id=f"{row_block_id(req_id, 'user_feedback')}:q{q_index}",
        label=PlainTextObject(text=prompt),
        element=element,
    )


def _build_confirmation_row(
    requirement: RunRequirement, run_id: str = "", awaiting_ts: Optional[str] = None
) -> List[Any]:
    req_id = requirement.id or ""
    name = _tool_name(requirement)
    args = _tool_args(requirement)
    button_value = encode_row_button_value(req_id, run_id, awaiting_ts)
    # Format args as bullet points in body (not subtitle which truncates)
    body_lines = [f"• {k}: `{render_arg_value(v)}`" for k, v in (args or {}).items()]
    body_text = "\n".join(body_lines) if body_lines else "_(no arguments)_"
    return [
        Card(
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
        ),
    ]


def build_confirmation_toggle_card(
    req_id: str,
    run_id: str,
    awaiting_ts: Optional[str],
    tool_name: str,
    body_text: str,
    selected: str,
) -> List[Any]:
    """Build a confirmation card with toggle state (Approve or Deny selected).

    When one button is selected, it gets styled + checkmark; the other is unstyled but clickable.
    """
    button_value = encode_row_button_value(req_id, run_id, awaiting_ts)

    if selected == "approve":
        approve_btn = ButtonElement(
            action_id=ACTION_ROW_APPROVE,
            text=PlainTextObject(text="Approved", emoji=True),
            style="primary",
            value=button_value,
        )
        deny_btn = ButtonElement(
            action_id=ACTION_ROW_REJECT,
            text=PlainTextObject(text="Deny", emoji=True),
            value=button_value,
        )
        block_id = f"rowact:{req_id}:confirmation:selected:approve"
    else:
        approve_btn = ButtonElement(
            action_id=ACTION_ROW_APPROVE,
            text=PlainTextObject(text="Approve", emoji=True),
            value=button_value,
        )
        deny_btn = ButtonElement(
            action_id=ACTION_ROW_REJECT,
            text=PlainTextObject(text="Denied", emoji=True),
            style="danger",
            value=button_value,
        )
        block_id = f"rowact:{req_id}:confirmation:selected:deny"

    return [
        Card(
            block_id=block_id,
            title=MarkdownTextObject(text=f"*{tool_name}*"),
            body=MarkdownTextObject(text=body_text),
            actions=[approve_btn, deny_btn],
        ),
    ]


def build_rejection_input_card(
    req_id: str,
    run_id: str,
    awaiting_ts: Optional[str],
    tool_name: str,
    original_title: str,
    original_body: str,
    original_pause_type: str = "confirmation",
) -> List[Any]:
    # Embed original card data in button values so Cancel can restore the Approve/Deny card
    button_value = encode_reject_card_value(
        req_id, run_id, awaiting_ts, original_title, original_body, original_pause_type
    )
    return [
        Card(
            block_id=f"rowact:{req_id}:rejection_input",
            title=MarkdownTextObject(text=f"*Deny: {tool_name}*"),
            subtitle=MarkdownTextObject(text="_Provide an optional reason for rejection_"),
            actions=[
                ButtonElement(
                    action_id=ACTION_REJECT_CONFIRM,
                    text=PlainTextObject(text="Confirm Rejection", emoji=True),
                    style="danger",
                    value=button_value,
                ),
                ButtonElement(
                    action_id=ACTION_REJECT_CANCEL,
                    text=PlainTextObject(text="Cancel", emoji=True),
                    value=button_value,
                ),
            ],
        ),
        InputBlock(
            block_id=f"reject_reason:{req_id}",
            label=PlainTextObject(text="Reason"),
            element=PlainTextInputElement(
                action_id=ACTION_REJECT_REASON,
                placeholder=PlainTextObject(text="Why are you rejecting this action?"),
                multiline=True,
            ),
            optional=True,
        ),
    ]


def build_original_row_card(
    req_id: str,
    run_id: str,
    awaiting_ts: Optional[str],
    original_title: str,
    original_body: str,
    pause_type: str = "confirmation",
) -> List[Any]:
    # Rebuild the Approve/Deny card from stored title/body (used by Cancel button)
    # Input fields for user_input/feedback/external are NOT restored — just the header card
    button_value = encode_row_button_value(req_id, run_id, awaiting_ts)
    return [
        Card(
            block_id=f"rowact:{req_id}:{pause_type}",
            title=MarkdownTextObject(text=original_title),
            body=MarkdownTextObject(text=original_body),
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
        ),
    ]


# Backward compat alias
build_original_confirmation_card = build_original_row_card


def _build_input_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    blocks: List[Any] = []
    schema = requirement.user_input_schema or []
    for ui_field in schema:
        blocks.append(_build_input_field(req_id, ui_field))
    return blocks


def _build_feedback_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    blocks: List[Any] = []
    schema = requirement.user_feedback_schema or []
    for i, question in enumerate(schema):
        blocks.append(_build_feedback_question(req_id, question, i))
    return blocks


def _build_external_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    return [
        InputBlock(
            block_id=f"{row_block_id(req_id, 'external_execution')}:result",
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
    from slack_sdk.models.blocks import ActionsBlock

    from agno.os.interfaces.slack.types import ACTION_SUBMIT, encode_submit_button_value, pause_block_id

    blocks: List[Any] = []
    processed = 0
    truncated_count = 0
    total = len(requirements)
    # Reserve 2 blocks for Submit button + truncation warning
    budget = MAX_MESSAGE_BLOCKS - 2

    for i, requirement in enumerate(requirements):
        kind = requirement.pause_type
        if kind == "confirmation":
            row_blocks = _build_confirmation_row(requirement, run_id=run_id, awaiting_ts=awaiting_ts)
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


def approval_task_id(req_id: str) -> str:
    return f"approval:{req_id}"


# Replaces interactive form with readonly summary so users see what was submitted
def response_blocks(
    original_blocks: List[Dict[str, Any]],
    state_values: Dict[str, Dict[str, Any]],
    requirements: List[RunRequirement],
) -> List[Dict[str, Any]]:
    preserved: List[Dict[str, Any]] = []
    submissions: List[str] = []

    confirmation_decisions: List[str] = []

    for block in original_blocks:
        btype = block.get("type")
        block_id = block.get("block_id", "")

        # Actions block contains Submit button which is no longer relevant
        if btype == "actions":
            continue

        # Decision marker sections — extract decision status for summary
        if btype == "section" and ":confirmation:decided:" in block_id:
            # Format: row:{req_id}:confirmation:decided:{approve|deny}
            parts = block_id.split(":")
            if len(parts) >= 5:
                decision = parts[4]
                req_id = parts[1]
                # Find matching requirement for tool name
                tool_name = "tool"
                for req in requirements:
                    if req.id == req_id:
                        tool_name = _tool_name(req)
                        break
                status = "Approved" if decision == "approve" else "Denied"
                confirmation_decisions.append(f"{status}: {tool_name}")
            continue

        # Skip rejection reason inputs — they're part of confirmation, not submission
        if block_id.startswith("reject_reason:"):
            continue

        # Keep card but strip actions (body shows tool args, Submitted card shows input values)
        if btype == "card":
            card_copy = {k: v for k, v in block.items() if k != "actions"}
            if ":selected:approve" in block_id:
                title = (card_copy.get("title") or {}).get("text", "")
                card_copy["title"] = {"type": "mrkdwn", "text": f"*Approved:* {title.replace('*', '')}"}
            elif ":selected:deny" in block_id:
                title = (card_copy.get("title") or {}).get("text", "")
                card_copy["title"] = {"type": "mrkdwn", "text": f"*Denied:* {title.replace('*', '')}"}
            preserved.append(card_copy)
            continue

        if btype != "input":
            preserved.append(block)
            continue

        label = (block.get("label") or {}).get("text", "")
        element = block.get("element") or {}
        action_id = element.get("action_id", "")
        etype = element.get("type")

        submitted = (state_values.get(block_id) or {}).get(action_id) or {}

        if etype == "plain_text_input":
            value = submitted.get("value") or "_(empty)_"
        elif etype == "static_select":
            opt = submitted.get("selected_option") or {}
            value = (opt.get("text") or {}).get("text") or opt.get("value") or "_(none)_"
        elif etype in ("checkboxes", "multi_static_select"):
            opts = submitted.get("selected_options") or []
            labels = [((o.get("text") or {}).get("text") or o.get("value") or "") for o in opts]
            value = ", ".join(labels) if labels else "_(none)_"
        else:
            value = "_(submitted)_"

        submissions.append(f"• {label}: `{value}`")

    # Only show Submitted card if there are input values (confirmation decisions are in their own cards)
    if not submissions:
        return preserved

    body_text = "\n".join(submissions)
    # Slack card body limit is 200 chars
    if len(body_text) > 200:
        body_text = body_text[:197] + "..."

    submission_card: Dict[str, Any] = {
        "type": "card",
        "title": {"type": "mrkdwn", "text": "*Submitted*"},
        "body": {"type": "mrkdwn", "text": body_text},
    }

    return preserved + [submission_card]
