from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

MAX_TEXT = 3000
MAX_ACTION_ID = 255
MAX_BLOCK_ID = 255
MAX_BUTTON_VALUE = 2000
MAX_OPTION_VALUE = 150
MAX_FALLBACK_TEXT = 500
MAX_SECTION_FIELDS = 10
MAX_ACTIONS_ELEMENTS = 25
MAX_CONTEXT_ELEMENTS = 10
MAX_MESSAGE_BLOCKS = 48
MAX_STATIC_OPTIONS = 100
MAX_CHOICE_OPTIONS = 10


class _Block(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PlainText(_Block):
    type: Literal["plain_text"] = "plain_text"
    text: str = Field(..., max_length=MAX_TEXT)
    emoji: bool = True


class Markdown(_Block):
    type: Literal["mrkdwn"] = "mrkdwn"
    text: str = Field(..., max_length=MAX_TEXT)


Text = Annotated[Union[PlainText, Markdown], Field(discriminator="type")]


class Option(_Block):
    text: PlainText
    value: str = Field(..., max_length=MAX_OPTION_VALUE)
    description: Optional[PlainText] = None


class ConfirmDialog(_Block):
    """Native Slack confirmation dialog — appears as a modal when the
    interactive element is triggered. Used for "are you sure?" prompts.
    https://docs.slack.dev/reference/block-kit/composition-objects/confirmation-dialog-object/"""

    title: PlainText = Field(..., description="max 100 chars")
    text: Text = Field(..., description="max 300 chars")
    confirm: PlainText = Field(..., description="max 30 chars")
    deny: PlainText = Field(..., description="max 30 chars")
    style: Optional[Literal["primary", "danger"]] = None


class Button(_Block):
    type: Literal["button"] = "button"
    action_id: str = Field(..., max_length=MAX_ACTION_ID)
    text: PlainText
    value: Optional[str] = Field(None, max_length=MAX_BUTTON_VALUE)
    style: Optional[Literal["primary", "danger"]] = None
    confirm: Optional[ConfirmDialog] = None


class StaticSelect(_Block):
    type: Literal["static_select"] = "static_select"
    action_id: str = Field(..., max_length=MAX_ACTION_ID)
    placeholder: PlainText
    options: List[Option] = Field(..., min_length=1, max_length=MAX_STATIC_OPTIONS)


class Checkboxes(_Block):
    type: Literal["checkboxes"] = "checkboxes"
    action_id: str = Field(..., max_length=MAX_ACTION_ID)
    options: List[Option] = Field(..., min_length=1, max_length=MAX_CHOICE_OPTIONS)


class PlainTextInput(_Block):
    type: Literal["plain_text_input"] = "plain_text_input"
    action_id: str = Field(..., max_length=MAX_ACTION_ID)
    placeholder: Optional[PlainText] = None
    initial_value: Optional[str] = None
    multiline: Optional[bool] = None


InputElement = Annotated[
    Union[Button, StaticSelect, Checkboxes, PlainTextInput],
    Field(discriminator="type"),
]


class Image(_Block):
    """Slack image element — standalone block OR Section accessory."""

    type: Literal["image"] = "image"
    image_url: str
    alt_text: str = Field("", max_length=MAX_TEXT)


class Section(_Block):
    type: Literal["section"] = "section"
    text: Optional[Text] = None
    fields: Optional[List[Text]] = Field(None, max_length=MAX_SECTION_FIELDS)
    accessory: Optional[Image] = None
    block_id: Optional[str] = Field(None, max_length=MAX_BLOCK_ID)


class Divider(_Block):
    type: Literal["divider"] = "divider"
    block_id: Optional[str] = Field(None, max_length=MAX_BLOCK_ID)


class Actions(_Block):
    type: Literal["actions"] = "actions"
    elements: List[Annotated[Union[Button, StaticSelect, Checkboxes], Field(discriminator="type")]] = Field(
        ..., min_length=1, max_length=MAX_ACTIONS_ELEMENTS
    )
    block_id: Optional[str] = Field(None, max_length=MAX_BLOCK_ID)


class Context(_Block):
    type: Literal["context"] = "context"
    elements: List[Annotated[Union[PlainText, Markdown, Image], Field(discriminator="type")]] = Field(
        ..., min_length=1, max_length=MAX_CONTEXT_ELEMENTS
    )
    block_id: Optional[str] = Field(None, max_length=MAX_BLOCK_ID)


class InputBlock(_Block):
    type: Literal["input"] = "input"
    label: PlainText
    element: InputElement
    hint: Optional[PlainText] = None
    optional: Optional[bool] = None
    block_id: Optional[str] = Field(None, max_length=MAX_BLOCK_ID)


class RichTextStyle(_Block):
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    strike: Optional[bool] = None
    code: Optional[bool] = None


class RichTextPlain(_Block):
    type: Literal["text"] = "text"
    text: str = Field(..., max_length=MAX_TEXT)
    style: Optional[RichTextStyle] = None


class RichTextLink(_Block):
    type: Literal["link"] = "link"
    url: str
    text: Optional[str] = Field(None, max_length=MAX_TEXT)


class RichTextSection(_Block):
    type: Literal["rich_text_section"] = "rich_text_section"
    elements: List[Annotated[Union[RichTextPlain, RichTextLink], Field(discriminator="type")]]


class RichText(_Block):
    """Rich-text block used inside task_card's `details` and `output` fields.
    Slack rejects mrkdwn in those slots — rich_text is the only supported
    formatting primitive. We expose only sections (no lists / code blocks /
    quote blocks yet — add as needed)."""

    type: Literal["rich_text"] = "rich_text"
    elements: List[RichTextSection]


class TaskCardSource(_Block):
    """Citation for a task_card — appears in the `sources` section when the
    card is expanded. Slack renders these as small link chips."""

    type: Literal["url"] = "url"
    url: str
    text: Optional[str] = Field(None, max_length=MAX_TEXT)


class TaskCard(_Block):
    """Slack's native task-card block — a collapsible row with a status icon,
    title, optional details/output (rich_text), and optional source chips.
    Designed for agent tool-call progress and HITL checkpoints.

    Valid statuses: `in_progress` (animated spinner), `completed` (green check),
    `error` (red). Slack rejects `pending` despite the obvious semantic fit —
    use `in_progress` for awaiting-user states.

    https://docs.slack.dev/reference/block-kit/blocks/task-card-block/
    """

    type: Literal["task_card"] = "task_card"
    task_id: str = Field(..., description="Stable id — reuse across updates to the same card")
    title: str = Field(..., max_length=MAX_TEXT)
    status: Literal["in_progress", "completed", "error"]
    details: Optional[RichText] = None
    output: Optional[RichText] = None
    sources: Optional[List[TaskCardSource]] = None
    block_id: Optional[str] = Field(None, max_length=MAX_BLOCK_ID)


Block = Annotated[
    Union[Section, Divider, Actions, Context, InputBlock, Image, TaskCard],
    Field(discriminator="type"),
]


class BlockKitMessage(_Block):
    text: str = Field(..., max_length=MAX_FALLBACK_TEXT)
    blocks: List[Block] = Field(..., min_length=1, max_length=MAX_MESSAGE_BLOCKS)

    def to_slack_payload(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "blocks": [b.model_dump(exclude_none=True, mode="json") for b in self.blocks],
        }
