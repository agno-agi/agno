"""Groq.format_message must write the json_object directive to the request payload,
not mutate the shared Message (which dropped it from the request and duplicated it on
every reuse)."""

from agno.models.groq.groq import Groq
from agno.models.message import Message

JSON_FORMAT = {"type": "json_object"}


def test_json_object_directive_reaches_payload():
    model = Groq(id="test")
    message = Message(role="system", content="You are a helpful assistant.")

    payload = model.format_message(message, response_format=JSON_FORMAT)

    assert "Your output should be in JSON format." in payload["content"]


def test_json_object_directive_does_not_mutate_message():
    model = Groq(id="test")
    message = Message(role="system", content="You are a helpful assistant.")

    model.format_message(message, response_format=JSON_FORMAT)
    # The shared Message is untouched, so a reuse doesn't accumulate duplicate directives.
    assert message.content == "You are a helpful assistant."
    second = model.format_message(message, response_format=JSON_FORMAT)
    assert second["content"].count("Your output should be in JSON format.") == 1
