from dataclasses import dataclass, field
from typing import Any, List, Optional

from agno.models.message import Message


@dataclass
class RunMessages:
    """Container for messages used in an Agent run.

    Attributes:
        messages: List of all messages to send to the model
        system_message: The system message for this run
        user_message: The user message for this run
        extra_messages: Extra messages added after the system and user messages
        run_response: Reference to the RunOutput for this run (used for metrics accumulation)
    """

    messages: List[Message] = field(default_factory=list)
    system_message: Optional[Message] = None
    user_message: Optional[Message] = None
    extra_messages: Optional[List[Message]] = None
    run_response: Optional[Any] = None  # RunOutput reference for metrics accumulation

    def get_input_messages(self) -> List[Message]:
        """Get the input messages for the model."""
        input_messages = []
        if self.system_message is not None:
            input_messages.append(self.system_message)
        if self.user_message is not None:
            input_messages.append(self.user_message)
        if self.extra_messages is not None:
            input_messages.extend(self.extra_messages)
        return input_messages
