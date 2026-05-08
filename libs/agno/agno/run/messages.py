from dataclasses import dataclass, field
from typing import List, Optional

from agno.models.message import Message


@dataclass
class RunMessages:
    """Container for messages used in an Agent run.

    Attributes:
        messages: List of all messages to send to the model
        system_message: The system message for this run
        user_message: The user message for this run
        extra_messages: Extra messages added after the system and user messages
    """

    messages: List[Message] = field(default_factory=list)
    system_message: Optional[Message] = None
    user_message: Optional[Message] = None
    extra_messages: Optional[List[Message]] = None

    def get_input_messages(self) -> List[Message]:
        """Get the input messages for the model.

        When ``messages`` has been assembled by the agent (system + history +
        user + tool messages), prefer it so callers receive the full context.
        ``extra_messages`` are appended without duplicating any already in
        ``messages``. Otherwise, fall back to the system + user + extra shape
        for callers that build the list piecewise.
        """
        if self.messages:
            input_messages = list(self.messages)
            if self.extra_messages:
                for msg in self.extra_messages:
                    if msg not in input_messages:
                        input_messages.append(msg)
            return input_messages

        input_messages = []
        if self.system_message is not None:
            input_messages.append(self.system_message)
        if self.user_message is not None:
            input_messages.append(self.user_message)
        if self.extra_messages is not None:
            input_messages.extend(self.extra_messages)
        return input_messages
