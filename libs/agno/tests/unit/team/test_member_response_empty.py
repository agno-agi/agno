"""#5278: empty member responses must be detected for team early-stop prevention."""
from types import SimpleNamespace

from agno.team._member_response import empty_member_response_message, member_run_is_empty


def test_none_response_is_empty():
    assert member_run_is_empty(None) is True


def test_none_content_without_tools_is_empty():
    assert member_run_is_empty(SimpleNamespace(content=None, tools=None)) is True
    assert member_run_is_empty(SimpleNamespace(content=None, tools=[])) is True


def test_empty_string_content_is_empty():
    assert member_run_is_empty(SimpleNamespace(content="   ", tools=None)) is True


def test_content_or_tools_not_empty():
    assert member_run_is_empty(SimpleNamespace(content="done", tools=None)) is False
    assert member_run_is_empty(
        SimpleNamespace(content=None, tools=[SimpleNamespace(result="x")])
    ) is False


def test_empty_message_mentions_not_completed():
    msg = empty_member_response_message("researcher")
    assert "researcher" in msg
    assert "NOT completed" in msg
