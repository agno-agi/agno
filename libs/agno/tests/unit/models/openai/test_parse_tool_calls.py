from typing import Optional

from agno.models.openai.chat import OpenAIChat


class _FakeChoiceDeltaToolCallFunction:
    def __init__(self, name: Optional[str] = None, arguments: Optional[str] = None):
        self.name = name
        self.arguments = arguments


class _FakeChoiceDeltaToolCall:
    def __init__(
        self,
        index: int,
        tool_id: Optional[str] = None,
        tool_type: Optional[str] = None,
        func_name: Optional[str] = None,
        func_args: Optional[str] = None,
    ):
        self.index = index
        self.id = tool_id
        self.type = tool_type
        if func_name is not None or func_args is not None:
            self.function = _FakeChoiceDeltaToolCallFunction(name=func_name, arguments=func_args)
        else:
            self.function = None


def test_parse_tool_calls_non_zero_index_creates_independent_dicts():
    """Ensure non-zero-based tool call index does not create shared dict references."""
    deltas = [
        _FakeChoiceDeltaToolCall(
            index=1, tool_id="call_abc", tool_type="function", func_name="get_weather", func_args='{"city":"NYC"}'
        ),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 2
    assert result[0] == {}
    assert result[1]["id"] == "call_abc"
    assert result[1]["function"]["name"] == "get_weather"
    assert result[0] is not result[1]


def test_parse_tool_calls_zero_index_works_normally():
    """Ensure standard zero-based tool calls still work."""
    deltas = [
        _FakeChoiceDeltaToolCall(
            index=0, tool_id="call_1", tool_type="function", func_name="search", func_args='{"q":"test"}'
        ),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 1
    assert result[0]["id"] == "call_1"
    assert result[0]["function"]["name"] == "search"


def test_parse_tool_calls_multiple_tools_independent():
    """Ensure multiple tool calls at different indices are independent."""
    deltas = [
        _FakeChoiceDeltaToolCall(index=0, tool_id="call_1", tool_type="function", func_name="tool_a", func_args="{}"),
        _FakeChoiceDeltaToolCall(index=1, tool_id="call_2", tool_type="function", func_name="tool_b", func_args="{}"),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 2
    assert result[0]["function"]["name"] == "tool_a"
    assert result[1]["function"]["name"] == "tool_b"
    assert result[0] is not result[1]


# ---------------------------------------------------------------------------
# Citation parsing (web-search models / OpenAI-compatible providers)
# ---------------------------------------------------------------------------


class _FakeURLCitation:
    def __init__(self, url: str, title: str):
        self.url = url
        self.title = title


class _FakeAnnotation:
    """Mimics openai.types.chat.chat_completion_message.Annotation (non-streaming)."""

    def __init__(self, url: str, title: str, annotation_type: str = "url_citation"):
        self.type = annotation_type
        self.url_citation = _FakeURLCitation(url, title)

    def model_dump(self):
        return {"type": self.type, "url_citation": {"url": self.url_citation.url, "title": self.url_citation.title}}


class _FakeMessage:
    def __init__(self, content="hello", annotations=None, with_annotations: bool = True):
        self.role = "assistant"
        self.content = content
        self.tool_calls = None
        self.audio = None
        # Older OpenAI SDKs have no `annotations` field at all
        if with_annotations:
            self.annotations = annotations


class _FakeResponse:
    def __init__(self, message: _FakeMessage):
        self.choices = [_FakeChoice(message)]
        self.usage = None
        self.id = None
        self.system_fingerprint = None
        self.model_extra = None


class _FakeChoice:
    def __init__(self, message: _FakeMessage):
        self.message = message


class _FakeDelta:
    def __init__(self, content=None, annotations=None, with_annotations: bool = True):
        self.content = content
        self.tool_calls = None
        # Streaming deltas surface annotations as dicts via model_extra
        if with_annotations:
            self.annotations = annotations


class _FakeChunk:
    def __init__(self, delta: _FakeDelta):
        self.choices = [_FakeStreamChoice(delta)]
        self.id = None
        self.system_fingerprint = None
        self.model_extra = None
        self.usage = None


class _FakeStreamChoice:
    def __init__(self, delta: _FakeDelta):
        self.delta = delta


def test_parse_response_extracts_url_citations():
    """Non-streaming: url_citation annotations are surfaced on model_response.citations."""
    message = _FakeMessage(
        annotations=[
            _FakeAnnotation(url="https://a.com", title="A"),
            _FakeAnnotation(url="https://b.com", title="B"),
        ]
    )
    model_response = OpenAIChat(id="gpt-4o")._parse_provider_response(_FakeResponse(message))

    assert model_response.citations is not None
    assert [c.url for c in model_response.citations.urls] == ["https://a.com", "https://b.com"]
    assert [c.title for c in model_response.citations.urls] == ["A", "B"]
    assert len(model_response.citations.raw) == 2


def test_parse_response_without_annotations_field_has_no_citations():
    """Non-streaming: a message lacking the `annotations` field (older SDK) must not raise."""
    model_response = OpenAIChat(id="gpt-4o")._parse_provider_response(
        _FakeResponse(_FakeMessage(with_annotations=False))
    )

    assert model_response.citations is None
    assert model_response.content == "hello"


def test_parse_response_empty_annotations_has_no_citations():
    """Non-streaming: an empty annotations list yields no citations."""
    model_response = OpenAIChat(id="gpt-4o")._parse_provider_response(_FakeResponse(_FakeMessage(annotations=[])))

    assert model_response.citations is None


def test_parse_response_delta_extracts_url_citations():
    """Streaming: dict url_citation annotations on the delta are surfaced on citations."""
    delta = _FakeDelta(
        content="hi",
        annotations=[
            {"type": "url_citation", "url_citation": {"url": "https://a.com", "title": "A"}},
            {"type": "url_citation", "url_citation": {"url": "https://b.com", "title": "B"}},
        ],
    )
    model_response = OpenAIChat(id="gpt-4o")._parse_provider_response_delta(_FakeChunk(delta))

    assert model_response.citations is not None
    assert [c.url for c in model_response.citations.urls] == ["https://a.com", "https://b.com"]
    assert [c.title for c in model_response.citations.urls] == ["A", "B"]


def test_parse_response_delta_without_annotations_has_no_citations():
    """Streaming: a delta without annotations must not raise and yields no citations."""
    model_response = OpenAIChat(id="gpt-4o")._parse_provider_response_delta(_FakeChunk(_FakeDelta(content="hi")))

    assert model_response.citations is None
    assert model_response.content == "hi"
