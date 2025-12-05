from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional, Set, Union

if TYPE_CHECKING:
    from agno.session.agent import AgentSession
    from agno.session.team import TeamSession


@dataclass
class CompressedContext:
    content: str
    message_ids: Set[str] = field(default_factory=set)
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "message_ids": list(self.message_ids),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompressedContext":
        updated_at = data.get("updated_at")
        return cls(
            content=data["content"],
            message_ids=set(data.get("message_ids", [])),
            updated_at=datetime.fromisoformat(updated_at) if updated_at else None,
        )


def get_compressed_context(
    session: Union["AgentSession", "TeamSession"],
) -> Optional[CompressedContext]:
    if session.session_data and "compressed_context" in session.session_data:
        return CompressedContext.from_dict(session.session_data["compressed_context"])
    return None


def set_compressed_context(
    session: Union["AgentSession", "TeamSession"],
    ctx: CompressedContext,
) -> None:
    if session.session_data is None:
        session.session_data = {}
    session.session_data["compressed_context"] = ctx.to_dict()

