from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from agno.os.interfaces.slack.block_kit import (
    MAX_MESSAGE_BLOCKS,
    MAX_SECTION_FIELDS,
    Actions,
    Button,
    Card,
    Checkboxes,
    ConfirmDialog,
    Context,
    Divider,
    InputBlock,
    Markdown,
    Option,
    PlainText,
    PlainTextInput,
    StaticSelect,
)
from agno.os.interfaces.slack.types import (
    ACTION_EXTERNAL_RESULT,
    ACTION_FEEDBACK_SELECT,
    ACTION_INPUT_FIELD_PREFIX,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    ACTION_SUBMIT,
    PauseType,
    pause_block_id,
    row_block_id,
)
from agno.run.requirement import RunRequirement

ARG_PREVIEW_MAX = 400
ARG_VALUE_MAX = 120


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def render_arg_value(value: Any) -> str:
    try:
        rendered = value if isinstance(value, str) else json.dumps(value, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return _truncate(rendered, ARG_VALUE_MAX)


def _tool_name(requirement: RunRequirement) -> str:
    tool = requirement.tool_execution
    return getattr(tool, "tool_name", None) or "tool"


def _tool_args(requirement: RunRequirement) -> Dict[str, Any]:
    tool = requirement.tool_execution
    return getattr(tool, "tool_args", None) or {}


def _classify_flags(
    *,
    user_feedback_schema: Any,
    requires_user_input: bool,
    external_execution_required: bool,
) -> PauseType:
    if user_feedback_schema:
        return "user_feedback"
    if external_execution_required:
        return "external_execution"
    if requires_user_input:
        return "user_input"
    return "confirmation"


def classify_tool_execution(tool_execution: Optional[Dict[str, Any]]) -> PauseType:
    if not tool_execution:
        return "confirmation"
    return _classify_flags(
        user_feedback_schema=tool_execution.get("user_feedback_schema"),
        requires_user_input=bool(tool_execution.get("requires_user_input")),
        external_execution_required=bool(tool_execution.get("external_execution_required")),
    )


def classify_requirement(requirement: RunRequirement) -> PauseType:
    tool = requirement.tool_execution
    if tool is None:
        return "confirmation"
    return _classify_flags(
        user_feedback_schema=getattr(tool, "user_feedback_schema", None),
        requires_user_input=bool(getattr(tool, "requires_user_input", False)),
        external_execution_required=bool(getattr(tool, "external_execution_required", False)),
    )


def _build_arg_fields(args: Optional[Dict[str, Any]]) -> List[Markdown]:
    if not args:
        return []
    fields: List[Markdown] = []
    total_chars = 0
    for key, value in args.items():
        if len(fields) >= MAX_SECTION_FIELDS - 1:
            remaining = len(args) - len(fields)
            if remaining > 0:
                fields.append(Markdown(text=f"_… {remaining} more_"))
            break
        rendered = f"*{key}:*\n{render_arg_value(value)}"
        if total_chars + len(rendered) > ARG_PREVIEW_MAX:
            remaining = len(args) - len(fields)
            fields.append(Markdown(text=f"_… {remaining} more_"))
            break
        fields.append(Markdown(text=rendered))
        total_chars += len(rendered)
    return fields


def _subtitle_from_args(args: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key, value in (args or {}).items():
        rendered = render_arg_value(value)
        if len(rendered) > 40:
            rendered = rendered[:37] + "…"
        parts.append(f"{key}: `{rendered}`")
    return " · ".join(parts) if parts else "_(no arguments)_"


def _confirmation_buttons(button_value: str, approve_confirm: Any, deny_confirm: Any) -> List[Button]:
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


def _build_confirm_dialogs(name: str, args: Dict[str, Any]) -> tuple[ConfirmDialog, ConfirmDialog]:
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


def _build_confirmation_row(requirement: RunRequirement, approval_id: str = "") -> List[Any]:
    req_id = requirement.id or ""
    name = _tool_name(requirement)
    args = _tool_args(requirement)
    approve_confirm, deny_confirm = _build_confirm_dialogs(name, args)
    return [
        Card(
            block_id=f"rowact:{req_id}:confirmation",
            title=Markdown(text=f"*Approve: {name}*"),
            subtitle=Markdown(text=_subtitle_from_args(args)),
            actions=_confirmation_buttons(f"{req_id}|{approval_id}", approve_confirm, deny_confirm),
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


_BUILDERS: Dict[str, Callable[[RunRequirement], List[Any]]] = {
    "confirmation": _build_confirmation_row,
    "user_input": _build_input_row,
    "user_feedback": _build_feedback_row,
    "external_execution": _build_external_row,
}


def _submit_actions_block(approval_id: str) -> Actions:
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


def build_pause_message(
    approval_id: str,
    requirements: List[RunRequirement],
) -> List[Any]:
    blocks: List[Any] = []
    processed = 0
    truncated_count = 0
    total = len(requirements)
    budget = MAX_MESSAGE_BLOCKS - 2

    for i, requirement in enumerate(requirements):
        kind = classify_requirement(requirement)
        if kind == "confirmation":
            row_blocks = _build_confirmation_row(requirement, approval_id=approval_id)
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

    needs_submit = any(classify_requirement(r) != "confirmation" for r in requirements[:processed])
    if needs_submit:
        blocks.append(_submit_actions_block(approval_id))
    return blocks


def approval_task_id(req_id: str) -> str:
    return f"approval:{req_id}"
