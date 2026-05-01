from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, get_args

from slack_sdk.models.blocks import (
    ActionsBlock as Actions,
)
from slack_sdk.models.blocks import (
    CheckboxesElement as Checkboxes,
)
from slack_sdk.models.blocks import (
    ConfirmObject as ConfirmDialog,
)
from slack_sdk.models.blocks import (
    ContextBlock as Context,
)
from slack_sdk.models.blocks import (
    DividerBlock as Divider,
)
from slack_sdk.models.blocks import (
    InputBlock,
)
from slack_sdk.models.blocks import (
    PlainTextInputElement as PlainTextInput,
)
from slack_sdk.models.blocks import (
    StaticSelectElement as StaticSelect,
)
from slack_sdk.models.blocks.basic_components import (
    MarkdownTextObject as Markdown,
)
from slack_sdk.models.blocks.basic_components import (
    Option,
)
from slack_sdk.models.blocks.basic_components import (
    PlainTextObject as PlainText,
)
from slack_sdk.models.blocks.block_elements import ButtonElement as Button
from slack_sdk.models.blocks.block_elements import ImageElement

from agno.os.interfaces.slack.types import (
    ACTION_EXTERNAL_RESULT,
    ACTION_FEEDBACK_SELECT,
    ACTION_INPUT_FIELD_PREFIX,
    ACTION_REJECT_CANCEL,
    ACTION_REJECT_CONFIRM,
    ACTION_REJECT_REASON,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    ACTION_SUBMIT,
    _tool_args,
    _tool_name,
    encode_reject_card_value,
    encode_row_button_value,
    encode_submit_button_value,
    pause_block_id,
    row_block_id,
)
from agno.run.requirement import RunRequirement
from agno.utils.serialize import json_serializer

# Slack caps messages at 50 blocks; reserve 2 for submit button + truncation warning
MAX_MESSAGE_BLOCKS = 48


@dataclass
class Card:
    # Card block shipped in Slack API 2024 but slack_sdk lacks model class
    actions: List[Button]
    icon: Optional[ImageElement] = None
    title: Optional[PlainText | Markdown] = None
    subtitle: Optional[PlainText | Markdown] = None
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


def _build_confirm_dialogs(name: str, args: Dict[str, Any]) -> tuple[ConfirmDialog, ConfirmDialog]:
    # Slack ConfirmDialog hard limits: title 100 chars, text 300 chars
    bullets: List[str] = []
    running = 0
    for key, value in (args or {}).items():
        line = f"• {key}: `{render_arg_value(value)}`"
        # 180 leaves room for footer text within 300 char limit
        if running + len(line) > 180:
            bullets.append(f"_… {len(args) - len(bullets)} more_")
            break
        bullets.append(line)
        running += len(line)
    args_block = "\n".join(bullets) if bullets else "_(no arguments)_"
    approve_text = (f"{args_block}\n\n_Approving will resume the agent run._")[:299]
    deny_text = args_block[:299]
    approve = ConfirmDialog(
        title=PlainText(text=f"Approve {name}?"[:100]),
        text=Markdown(text=approve_text),
        confirm=PlainText(text="Yes, approve"),
        deny=PlainText(text="Cancel"),
        style="primary",
    )
    deny = ConfirmDialog(
        title=PlainText(text=f"Deny {name}?"[:100]),
        text=Markdown(text=deny_text),
        confirm=PlainText(text="Yes, deny"),
        deny=PlainText(text="Cancel"),
        style="danger",
    )
    return approve, deny


# Slack lacks native boolean input; checkbox implies multi-select which is confusing
_BOOL_OPTIONS = [
    Option(text=PlainText(text="True"), value="true"),
    Option(text=PlainText(text="False"), value="false"),
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
        options = [Option(text=PlainText(text=str(arg)), value=str(arg)) for arg in literal_args]
        element = StaticSelect(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainText(text="Select"),
            options=options,
        )

    # Check for Enum subclass — renders as dropdown with enum members as options
    elif isinstance(field_type, type) and issubclass(field_type, Enum):
        options = [Option(text=PlainText(text=member.name), value=member.name) for member in field_type]
        element = StaticSelect(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainText(text="Select"),
            options=options,
        )

    elif type_name == "bool":
        element = StaticSelect(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainText(text="Select"),
            options=_BOOL_OPTIONS,
        )

    if element is None:
        multiline = type_name in ("list", "dict")
        initial_value: Optional[str] = None
        if initial_raw is not None:
            initial_value = initial_raw if isinstance(initial_raw, str) else json.dumps(initial_raw, default=str)
        element = PlainTextInput(
            action_id=f"{ACTION_INPUT_FIELD_PREFIX}{name}",
            placeholder=PlainText(text=f"Enter {name}"),
            initial_value=initial_value,
            multiline=multiline or None,
        )

    return InputBlock(
        block_id=f"{row_block_id(req_id, 'user_input')}:{name}",
        label=PlainText(text=name),
        element=element,
        hint=PlainText(text=description) if description else None,
    )


def _option_to_slack(option: Any, index: int) -> Option:
    label = getattr(option, "label", f"option-{index}")
    description = getattr(option, "description", None)
    return Option(
        text=PlainText(text=label),
        value=label,
        description=PlainText(text=description) if description else None,
    )


def _build_feedback_question(req_id: str, question: Any, q_index: int) -> InputBlock:
    prompt = getattr(question, "question", f"Question {q_index + 1}")
    options = getattr(question, "options", None) or []
    multi_select = bool(getattr(question, "multi_select", False))

    slack_options = [_option_to_slack(opt, i) for i, opt in enumerate(options)]

    element: Any
    if multi_select:
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
        block_id=f"{row_block_id(req_id, 'user_feedback')}:q{q_index}",
        label=PlainText(text=prompt),
        element=element,
    )


def _build_confirmation_row(
    requirement: RunRequirement, run_id: str = "", awaiting_ts: Optional[str] = None
) -> List[Any]:
    req_id = requirement.id or ""
    name = _tool_name(requirement)
    args = _tool_args(requirement)
    button_value = encode_row_button_value(req_id, run_id, awaiting_ts)
    # Format args as "key: `value` · key2: `value2`" for card subtitle
    subtitle_parts = [f"{k}: `{render_arg_value(v)}`" for k, v in (args or {}).items()]
    subtitle = " · ".join(subtitle_parts) if subtitle_parts else "_(no arguments)_"
    return [
        Card(
            block_id=f"rowact:{req_id}:confirmation",
            title=Markdown(text=f"*{name}*"),
            subtitle=Markdown(text=subtitle),
            actions=[
                Button(
                    action_id=ACTION_ROW_APPROVE,
                    text=PlainText(text="Approve", emoji=True),
                    style="primary",
                    value=button_value,
                ),
                Button(
                    action_id=ACTION_ROW_REJECT,
                    text=PlainText(text="Deny", emoji=True),
                    style="danger",
                    value=button_value,
                ),
            ],
        ),
    ]


def build_rejection_input_card(
    req_id: str,
    run_id: str,
    awaiting_ts: Optional[str],
    tool_name: str,
    original_title: str,
    original_subtitle: str,
) -> List[Any]:
    # Embed original card data in button values so Cancel can restore the Approve/Deny card
    button_value = encode_reject_card_value(req_id, run_id, awaiting_ts, original_title, original_subtitle)
    return [
        Card(
            block_id=f"rowact:{req_id}:rejection_input",
            title=Markdown(text=f"*Deny: {tool_name}*"),
            subtitle=Markdown(text="_Provide an optional reason for rejection_"),
            actions=[
                Button(
                    action_id=ACTION_REJECT_CONFIRM,
                    text=PlainText(text="Confirm Rejection", emoji=True),
                    style="danger",
                    value=button_value,
                ),
                Button(
                    action_id=ACTION_REJECT_CANCEL,
                    text=PlainText(text="Cancel", emoji=True),
                    value=button_value,
                ),
            ],
        ),
        InputBlock(
            block_id=f"reject_reason:{req_id}",
            label=PlainText(text="Reason"),
            element=PlainTextInput(
                action_id=ACTION_REJECT_REASON,
                placeholder=PlainText(text="Why are you rejecting this action?"),
                multiline=True,
            ),
            optional=True,
        ),
    ]


def build_original_confirmation_card(
    req_id: str,
    run_id: str,
    awaiting_ts: Optional[str],
    original_title: str,
    original_subtitle: str,
) -> List[Any]:
    # Rebuild the Approve/Deny card from stored title/subtitle (used by Cancel button)
    button_value = encode_row_button_value(req_id, run_id, awaiting_ts)
    return [
        Card(
            block_id=f"rowact:{req_id}:confirmation",
            title=Markdown(text=original_title),
            subtitle=Markdown(text=original_subtitle),
            actions=[
                Button(
                    action_id=ACTION_ROW_APPROVE,
                    text=PlainText(text="Approve", emoji=True),
                    style="primary",
                    value=button_value,
                ),
                Button(
                    action_id=ACTION_ROW_REJECT,
                    text=PlainText(text="Deny", emoji=True),
                    style="danger",
                    value=button_value,
                ),
            ],
        ),
    ]


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
            label=PlainText(text="Result"),
            element=PlainTextInput(
                action_id=ACTION_EXTERNAL_RESULT,
                placeholder=PlainText(text="Paste the execution output here"),
                multiline=True,
            ),
        ),
    ]


# Confirmation is special-cased in build_pause_message because it needs run_id + awaiting_ts
_BUILDERS: Dict[str, Callable[[RunRequirement], List[Any]]] = {
    "user_input": _build_input_row,
    "user_feedback": _build_feedback_row,
    "external_execution": _build_external_row,
}


def build_pause_message(
    run_id: str,
    requirements: List[RunRequirement],
    awaiting_ts: Optional[str] = None,
) -> List[Any]:
    blocks: List[Any] = []
    processed = 0
    truncated_count = 0
    total = len(requirements)
    budget = MAX_MESSAGE_BLOCKS - 2

    for i, requirement in enumerate(requirements):
        kind = requirement.pause_type
        if kind == "confirmation":
            row_blocks = _build_confirmation_row(requirement, run_id=run_id, awaiting_ts=awaiting_ts)
        else:
            row_blocks = _BUILDERS[kind](requirement)
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

    needs_submit = any(r.pause_type != "confirmation" for r in requirements[:processed])
    if needs_submit:
        blocks.append(
            Actions(
                block_id=pause_block_id(run_id),
                elements=[
                    Button(
                        action_id=ACTION_SUBMIT,
                        text=PlainText(text="Submit"),
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
    submissions: List[Dict[str, Any]] = []

    for block in original_blocks:
        btype = block.get("type")

        # Actions block contains Submit button which is no longer relevant
        if btype == "actions":
            continue

        # Keep card structure but strip approve/deny buttons
        if btype == "card":
            preserved.append({k: v for k, v in block.items() if k != "actions"})
            continue

        if btype != "input":
            preserved.append(block)
            continue

        label = (block.get("label") or {}).get("text", "")
        element = block.get("element") or {}
        block_id = block.get("block_id", "")
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

        submissions.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{label}*\n{value}"},
            }
        )

    if not submissions:
        return preserved

    body_lines = [(s.get("text") or {}).get("text", "") for s in submissions]

    # Use first tool name as title so audit trail shows what was approved
    card_title = "Submitted"
    for req in requirements:
        tool = _tool_name(req)
        if tool:
            card_title = tool
            break

    body_text = "\n\n".join(body_lines)
    if len(body_text) > 200:  # Slack Card body renders poorly past ~200 chars
        body_text = body_text[:197] + "..."

    submission_card: Dict[str, Any] = {
        "type": "card",
        "title": {"type": "mrkdwn", "text": card_title},
        "body": {"type": "mrkdwn", "text": body_text},
    }

    return preserved + [submission_card]
