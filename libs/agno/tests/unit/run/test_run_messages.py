from agno.models.message import Message
from agno.run.messages import RunMessages


def test_get_input_messages_uses_assembled_messages() -> None:
    assembled_messages = [
        Message(role="system", content="You are helpful"),
        Message(role="user", content="My name is Alex"),
        Message(role="assistant", content="Nice to meet you, Alex"),
        Message(role="user", content="What is my name?"),
    ]
    run_messages = RunMessages(
        messages=assembled_messages,
        system_message=Message(role="system", content="fallback system"),
        user_message=Message(role="user", content="fallback user"),
        extra_messages=[Message(role="assistant", content="fallback assistant")],
    )

    input_messages = run_messages.get_input_messages()

    assert input_messages == assembled_messages
    assert input_messages is not assembled_messages


def test_get_input_messages_falls_back_to_parts_when_unassembled() -> None:
    system_message = Message(role="system", content="You are helpful")
    user_message = Message(role="user", content="Hello")
    extra_messages = [Message(role="assistant", content="Hi")]
    run_messages = RunMessages(
        system_message=system_message,
        user_message=user_message,
        extra_messages=extra_messages,
    )

    assert run_messages.get_input_messages() == [
        system_message,
        user_message,
        *extra_messages,
    ]
