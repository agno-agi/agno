from agno.models.message import Message
from agno.utils.message import get_text_from_message


def test_list_of_strings_returns_joined_text():
    assert get_text_from_message(["hello", "world"]) == "hello\nworld"


def test_list_of_strings_containing_type_or_role():
    assert get_text_from_message(["what type of file is this?"]) == "what type of file is this?"
    assert get_text_from_message(["explain your role"]) == "explain your role"


def test_list_of_non_text_items_returns_empty_string():
    assert get_text_from_message([123]) == ""


def test_dict_lists_skip_non_dict_items():
    assert get_text_from_message([{"type": "text", "text": "a"}, None]) == "a"
    assert get_text_from_message([{"role": "user", "content": "hi"}, None]) == "hi"


def test_existing_list_inputs_unchanged():
    assert get_text_from_message([]) == ""
    assert get_text_from_message([Message(role="user", content="hi"), Message(role="assistant", content="yo")]) == "hi"
    assert get_text_from_message([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\nb"
    assert get_text_from_message([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]) == "hi"
