from agno.run.agent import RunContentEvent
from agno.utils.pprint import _stringify_stream_chunk, pprint_run_response


def test_stringify_stream_chunk_dict():
    assert _stringify_stream_chunk({"city": "Paris"}) == '{"city": "Paris"}'


def test_stringify_stream_chunk_str():
    assert _stringify_stream_chunk("hello") == "hello"


def test_pprint_streaming_dict_content_does_not_crash():
    pprint_run_response([RunContentEvent(content={"city": "Paris"})])
