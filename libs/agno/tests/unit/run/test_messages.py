from agno.models.message import Message
from agno.run.messages import RunMessages


def test_get_input_messages_returns_assembled_messages_first():
    history = Message(role="user", content="earlier question")
    current = Message(role="user", content="current question")
    fallback = Message(role="user", content="fallback only")

    run_messages = RunMessages(messages=[history, current], user_message=fallback)

    assert run_messages.get_input_messages() == [history, current]


def test_get_input_messages_keeps_field_fallback():
    system = Message(role="system", content="system")
    user = Message(role="user", content="user")
    extra = Message(role="assistant", content="extra")

    run_messages = RunMessages(system_message=system, user_message=user, extra_messages=[extra])

    assert run_messages.get_input_messages() == [system, user, extra]
