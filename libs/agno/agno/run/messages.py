from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from agno.models.message import Message


@dataclass
class RunMessages:
    """Container for messages used in an Agent run.

    Attributes:
        messages: List of all messages to send to the model
        system_message: The system message for this run
        user_message: The user message for this run
        extra_messages: Extra messages added after the system and user messages
        run_input_messages: Messages given as the run input in list form, when no user_message is built
        reasoning_messages: Reasoning added for the model to read before it responds
        events: Events raised while assembling these messages, for the caller
            to emit. Assembly is not a generator, so anything worth streaming
            (compaction, for one) is collected here instead of yielded.
    """

    messages: List[Message] = field(default_factory=list)
    system_message: Optional[Message] = None
    user_message: Optional[Message] = None
    extra_messages: Optional[List[Message]] = None
    run_input_messages: Optional[List[Message]] = None
    reasoning_messages: Optional[List[Message]] = None
    events: List[Any] = field(default_factory=list)

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

    def add_reasoning_message(self, message: Message) -> None:
        """Add reasoning for the model to read. It is context for the response, not part of it."""
        self.messages.append(message)
        if self.reasoning_messages is None:
            self.reasoning_messages = []
        self.reasoning_messages.append(message)

    def get_response_messages(self) -> List[Message]:
        """Get the messages this run produced: everything after its input, history and reasoning."""
        input_ids = {id(m) for m in self.get_input_messages()}
        input_ids.update(id(m) for m in self.run_input_messages or [])
        input_ids.update(id(m) for m in self.reasoning_messages or [])
        start = 0
        for index, message in enumerate(self.messages):
            if message.from_history or id(message) in input_ids:
                start = index + 1
        return self.messages[start:]

    def get_content(self, default: Any = None) -> Any:
        """Get the run's content from the messages it produced, or default when no model call added a message."""
        response_messages = self.get_response_messages()
        if not any(message.role == "assistant" for message in response_messages):
            return default
        return get_run_content(response_messages)


def get_run_content(messages: Sequence[Message]) -> Optional[str]:
    """Derive a run's content from the messages it produced.

    The content is the last non-empty assistant text. Text written before a tool call stays in
    its own assistant message. Results of tools marked show_result are kept, in message order.
    Returns None when the messages hold neither.
    """
    answer_index: Optional[int] = None
    for index, message in enumerate(messages):
        if message.role == "assistant" and message.get_content_string().strip():
            answer_index = index

    parts: List[str] = []
    for index, message in enumerate(messages):
        if index == answer_index:
            parts.append(message.get_content_string())
        elif message.show_result and message.shown_content is not None:
            parts.append(message.shown_content)
        elif message.show_result and message.content is not None:
            parts.append(message.content if isinstance(message.content, str) else message.get_content_string())
    return "".join(parts) if parts else None
