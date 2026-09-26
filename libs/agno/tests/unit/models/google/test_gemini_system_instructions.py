import pytest

pytest.importorskip("google.genai")

from agno.models.google.gemini import Gemini
from agno.models.message import Message


@pytest.mark.parametrize("roles", [("system", "system"), ("system", "developer"), ("developer", "system")])
def test_all_system_instructions_are_preserved(roles):
    model = Gemini()
    messages = [
        Message(role=roles[0], content="Use only the supplied evidence."),
        Message(role=roles[1], content="Respond in French."),
        Message(role="user", content="Summarize the document."),
    ]

    contents, instruction = model._format_messages(messages)

    assert instruction == ["Use only the supplied evidence.", "Respond in French."]
    assert len(contents) == 1
    assert contents[0].role == "user"
    assert messages[0].content == "Use only the supplied evidence."


def test_empty_system_message_does_not_erase_instructions():
    _, instruction = Gemini()._format_messages(
        [Message(role="system", content="Keep the policy."), Message(role="developer", content=None)]
    )
    assert instruction == "Keep the policy."


def test_list_instructions_are_flattened_without_mutating_messages():
    instructions = ["First constraint.", "Second constraint."]
    _, instruction = Gemini()._format_messages(
        [Message(role="system", content=instructions), Message(role="developer", content="Third constraint.")]
    )
    assert instruction == ["First constraint.", "Second constraint.", "Third constraint."]
    assert instructions == ["First constraint.", "Second constraint."]
