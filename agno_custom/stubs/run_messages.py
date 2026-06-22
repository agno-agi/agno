"""V1-compatible stub for RunMessages class (V2 changed message handling)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class RunMessages:
    """V1-compatible stub for RunMessages.

    In V2, message handling is done through agno.models.message.Message
    and agno.session management.
    This stub provides V1 interface compatibility.
    """

    messages: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, message: Dict[str, Any]) -> None:
        """Add a message to the list."""
        self.messages.append(message)

    def get_messages(self) -> List[Dict[str, Any]]:
        """Get all messages."""
        return self.messages

    def clear(self) -> None:
        """Clear all messages."""
        self.messages.clear()
