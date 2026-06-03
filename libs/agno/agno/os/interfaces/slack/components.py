from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from slack_sdk.models.blocks.basic_components import MarkdownTextObject, PlainTextObject
from slack_sdk.models.blocks.block_elements import ButtonElement, ImageElement


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
