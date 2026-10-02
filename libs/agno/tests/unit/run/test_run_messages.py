from agno.models.message import Message
from agno.run.messages import RunMessages


def test_get_input_messages_uses_assembled_messages() -> None:
    system = Message(role="system", content="You are helpful.")
    history_user = Message(role="user", content="My name is Alex.", from_history=True)
    history_assistant = Message(role="assistant", content="Hi Alex.", from_history=True)
    current_user = Message(role="user", content="What's my name?")

    run_messages = RunMessages(
        messages=[system, history_user, history_assistant, current_user],
        system_message=system,
        user_message=current_user,
    )

    assert run_messages.get_input_messages() == [system, history_user, history_assistant, current_user]


def test_get_input_messages_falls_back_to_fields() -> None:
    system = Message(role="system", content="You are helpful.")
    extra = Message(role="user", content="Additional context")
    current_user = Message(role="user", content="What's my name?")

    run_messages = RunMessages(system_message=system, user_message=current_user, extra_messages=[extra])

    assert run_messages.get_input_messages() == [system, current_user, extra]
