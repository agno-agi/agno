from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from textwrap import dedent
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, Field

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.prompts import get_json_output_prompt
from agno.utils.string import parse_response_model_str


@dataclass
class SessionSummary:
    """Model for Session Summary."""

    summary: str
    topics: Optional[List[str]] = None
    last_updated: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            "summary": self.summary,
            "topics": self.topics,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionSummary":
        last_updated = data.get("last_updated")
        if last_updated:
            data["last_updated"] = datetime.fromisoformat(last_updated)
        return cls(**data)


class SessionSummaryResponse(BaseModel):
    """Model for Session Summary."""

    summary: str = Field(
        ...,
        description="Summary of the session. Be concise and focus on only important information. Do not make anything up.",
    )
    topics: Optional[List[str]] = Field(None, description="Topics discussed in the session.")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True, indent=2)
