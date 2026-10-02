"""Unit tests for ``RunMessages.get_input_messages``.

Regression: when an agent runs with ``add_history_to_context=True`` the agent
populates ``run_messages.messages`` with [system, *history, user, ...] before
invoking downstream consumers (e.g. the reasoning manager). The previous
implementation rebuilt the list from ``system_message + user_message +
extra_messages`` and silently dropped the history, so a reasoning sub-agent
seeded from this method received no prior context.

``get_input_messages`` now prefers the assembled ``messages`` list and only
falls back to the piecewise shape when ``messages`` is empty.
"""

from agno.models.message import Message
from agno.run.messages import RunMessages


def test_returns_assembled_messages_when_populated() -> None:
    system = Message(role="system", content="sys")
    history_user = Message(role="user", content="My name is Alex.")
    history_assistant = Message(role="assistant", content="Hi Alex.")
    current_user = Message(role="user", content="What's my name?")

    rm = RunMessages(
        messages=[system, history_user, history_assistant, current_user],
        system_message=system,
        user_message=current_user,
    )

    out = rm.get_input_messages()

    assert out == [system, history_user, history_assistant, current_user]
    # Defensive copy: callers can mutate without affecting the original.
    assert out is not rm.messages


def test_falls_back_to_piecewise_when_messages_empty() -> None:
    system = Message(role="system", content="sys")
    user = Message(role="user", content="hi")
    extra = Message(role="user", content="more")

    rm = RunMessages(system_message=system, user_message=user, extra_messages=[extra])

    assert rm.get_input_messages() == [system, user, extra]


def test_appends_extra_messages_not_already_in_messages() -> None:
    system = Message(role="system", content="sys")
    user = Message(role="user", content="hi")
    extra_new = Message(role="user", content="follow up")

    rm = RunMessages(
        messages=[system, user],
        system_message=system,
        user_message=user,
        extra_messages=[extra_new],
    )

    assert rm.get_input_messages() == [system, user, extra_new]


def test_dedupes_extra_messages_already_in_messages() -> None:
    system = Message(role="system", content="sys")
    user = Message(role="user", content="hi")
    # Same Message object referenced from both messages and extra_messages —
    # must not be duplicated in the output.
    rm = RunMessages(
        messages=[system, user],
        system_message=system,
        user_message=user,
        extra_messages=[user],
    )

    assert rm.get_input_messages() == [system, user]


def test_returns_empty_list_when_nothing_set() -> None:
    assert RunMessages().get_input_messages() == []
