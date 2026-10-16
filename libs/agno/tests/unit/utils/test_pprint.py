from pydantic import BaseModel
from rich.json import JSON

from agno.run.agent import RunContentEvent
from agno.utils.pprint import _update_stream_display, pprint_run_response


class _City(BaseModel):
    city: str


def test_update_stream_display_concatenates_string_tokens():
    assert _update_stream_display("Hel", "lo") == "Hello"


def test_update_stream_display_dict_is_json_object_not_a_token():
    result = _update_stream_display("", {"city": "Paris"})
    assert isinstance(result, JSON)
    assert '"city"' in result.text
    assert "Paris" in result.text


def test_update_stream_display_does_not_concat_dict_onto_tokens():
    result = _update_stream_display("hello", {"city": "Paris"})
    assert isinstance(result, str)
    assert result.startswith("hello")
    assert '"city"' in result
    assert not result.startswith("hello{")


def test_update_stream_display_model_is_json_object():
    result = _update_stream_display("", _City(city="Paris"))
    assert isinstance(result, JSON)
    assert "Paris" in result.text


def test_pprint_streaming_dict_content_does_not_crash():
    pprint_run_response([RunContentEvent(content={"city": "Paris"})])


def test_pprint_streaming_strings_then_dict_does_not_crash():
    pprint_run_response(
        [
            RunContentEvent(content="hello"),
            RunContentEvent(content={"city": "Paris"}),
        ]
    )
