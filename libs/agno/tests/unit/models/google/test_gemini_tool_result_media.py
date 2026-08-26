from agno.media import Image
from agno.models.google.gemini import Gemini
from agno.models.message import Message


def test_tool_result_media_is_sent_in_a_following_user_turn():
    messages = [
        Message(role="assistant", content="", tool_calls=[{"function": {"name": "read_file", "arguments": "{}"}}]),
        Message(
            role="tool",
            tool_call_id="call-1",
            tool_name="read_file",
            content="File is ready",
            images=[Image(content=b"image-bytes", mime_type="image/png")],
        ),
    ]

    formatted, _ = Gemini()._format_messages(messages)

    assert len(formatted) == 3
    assert formatted[1].role == "user"
    assert formatted[1].parts[0].function_response is not None
    assert formatted[2].role == "user"
    assert formatted[2].parts[0].inline_data is not None


def test_tool_results_without_media_still_merge_with_adjacent_user_content():
    messages = [
        Message(role="user", content="before"),
        Message(role="tool", tool_call_id="call-1", tool_name="read_file", content="File is ready"),
        Message(role="user", content="after"),
    ]

    formatted, _ = Gemini()._format_messages(messages)

    assert len(formatted) == 1
    assert formatted[0].role == "user"
    assert formatted[0].parts[0].text == "before"
    assert formatted[0].parts[1].function_response is not None
    assert formatted[0].parts[2].text == "after"
