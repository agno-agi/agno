from typing import List

from agno.models.message import Message
from agno.run.messages import RunMessages


def extract_text_from_messages(messages: List[Message]) -> str:
    """Extract text content from a list of messages.

    Args:
        messages: List of Message objects to extract text from.

    Returns:
        Space-joined string of all text content.
    """
    texts = []
    for msg in messages:
        if msg.content:
            if isinstance(msg.content, str):
                texts.append(msg.content)
            elif isinstance(msg.content, list):
                for item in msg.content:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict) and "text" in item:
                        texts.append(str(item["text"]))
    return " ".join(texts)


def extract_all_text_from_run_messages(run_messages: RunMessages) -> str:
    """Extract all text from a RunMessages container.

    Args:
        run_messages: RunMessages with full conversation context.

    Returns:
        Space-joined string of all text content.
    """
    all_messages: List[Message] = []

    if run_messages.messages:
        all_messages.extend(run_messages.messages)
    if run_messages.system_message:
        all_messages.append(run_messages.system_message)
    if run_messages.user_message:
        all_messages.append(run_messages.user_message)
    if run_messages.extra_messages:
        all_messages.extend(run_messages.extra_messages)

    return extract_text_from_messages(all_messages)
