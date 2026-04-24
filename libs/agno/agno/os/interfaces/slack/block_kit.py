from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from slack_sdk.models.blocks import (
    ActionsBlock,
    CheckboxesElement,
    ConfirmObject,
    ContextBlock,
    DividerBlock,
    InputBlock,
    PlainTextInputElement,
    RichTextBlock,
    SectionBlock,
    StaticSelectElement,
    TaskCardBlock,
)
from slack_sdk.models.blocks.basic_components import (
    MarkdownTextObject,
    Option,
    PlainTextObject,
)
from slack_sdk.models.blocks.block_elements import ButtonElement, ImageElement

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

PlainText = PlainTextObject
Markdown = MarkdownTextObject
Button = ButtonElement
StaticSelect = StaticSelectElement
Checkboxes = CheckboxesElement
PlainTextInput = PlainTextInputElement
ConfirmDialog = ConfirmObject
Section = SectionBlock
Divider = DividerBlock
Actions = ActionsBlock
Context = ContextBlock
Image = ImageElement
TaskCard = TaskCardBlock
RichText = RichTextBlock


@dataclass
class RichTextStyle:
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    strike: Optional[bool] = None
    code: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class RichTextPlain:
    text: str
    style: Optional[RichTextStyle] = None
    type: str = "text"

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"type": self.type, "text": self.text}
        if self.style:
            result["style"] = self.style.to_dict()
        return result


@dataclass
class RichTextLink:
    url: str
    text: Optional[str] = None
    type: str = "link"

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"type": self.type, "url": self.url}
        if self.text:
            result["text"] = self.text
        return result


@dataclass
class RichTextSection:
    elements: List[RichTextPlain | RichTextLink]
    type: str = "rich_text_section"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "elements": [e.to_dict() for e in self.elements],
        }


@dataclass
class TaskCardSource:
    url: str
    text: Optional[str] = None
    type: str = "url"

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"type": self.type, "url": self.url}
        if self.text:
            result["text"] = self.text
        return result


@dataclass
class Card:
    """Slack card block for HITL approval prompts. Not in SDK yet."""

    actions: List[ButtonElement]
    icon: Optional[ImageElement] = None
    title: Optional[PlainTextObject | MarkdownTextObject] = None
    subtitle: Optional[PlainTextObject | MarkdownTextObject] = None
    block_id: Optional[str] = None
    type: str = "card"

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


Block = SectionBlock | DividerBlock | ActionsBlock | ContextBlock | InputBlock | ImageElement | TaskCardBlock | Card


@dataclass
class BlockKitMessage:
    text: str
    blocks: List[Block] = field(default_factory=list)

    def to_slack_payload(self) -> Dict[str, Any]:
        block_dicts: List[Any] = []
        for b in self.blocks:
            if hasattr(b, "to_dict"):
                block_dicts.append(b.to_dict())
            else:
                block_dicts.append(b)
        return {
            "text": self.text,
            "blocks": block_dicts,
        }
