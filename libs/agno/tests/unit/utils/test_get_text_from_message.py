from agno.utils.message import get_text_from_message


def test_list_of_plain_strings():
    # A plain string was treated as a dict: `"type" in message[0]` is a substring
    # test, so a string containing "type" crashed (str.get) and one without it was
    # silently dropped.
    assert get_text_from_message(["what data type is this?"]) == "what data type is this?"
    assert get_text_from_message(["hello world"]) == "hello world"
    assert get_text_from_message(["line one", "line two"]) == "line one\nline two"


def test_list_of_content_dicts_still_works():
    assert get_text_from_message([{"type": "text", "text": "hi"}]) == "hi"
    assert get_text_from_message([{"role": "user", "content": "hey"}]) == "hey"


def test_empty_list():
    assert get_text_from_message([]) == ""
