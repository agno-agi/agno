"""Unit tests for ContextProvider base class and shared types."""

import json
from dataclasses import asdict

import pytest

from agno.context import Answer, ContextMode, ContextProvider, Document, Status
from agno.context.provider import _sanitize_id


class StubProvider(ContextProvider):
    """Minimal concrete provider for testing the base class."""

    def __init__(self, *, answer_text: str = "stub", **kwargs):
        super().__init__(**kwargs)
        self._answer_text = answer_text

    def query(self, question: str) -> Answer:
        return Answer(text=self._answer_text, results=[Document(id="1", name="doc")])

    async def aquery(self, question: str) -> Answer:
        return self.query(question)

    def status(self) -> Status:
        return Status(ok=True, detail="stub")

    async def astatus(self) -> Status:
        return self.status()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


def test_status_dataclass():
    s = Status(ok=True)
    assert s.ok is True
    assert s.detail == ""
    s2 = Status(ok=False, detail="boom")
    assert s2.detail == "boom"


def test_document_defaults():
    d = Document(id="abc", name="file.txt")
    assert d.uri is None
    assert d.kind == "file"
    assert d.snippet is None


def test_answer_defaults():
    a = Answer()
    assert a.results == []
    assert a.text is None


# ---------------------------------------------------------------------------
# _sanitize_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("web", "web"),
        ("Web-Context", "web_context"),
        ("!!! weird ???", "weird"),
        ("multi  space", "multi_space"),
        ("", "context"),
        ("---", "context"),
    ],
)
def test_sanitize_id(raw, expected):
    assert _sanitize_id(raw) == expected


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_provider_construction_defaults():
    p = StubProvider(id="web")
    assert p.id == "web"
    assert p.name == "web"
    assert p.mode == ContextMode.default
    assert p.model is None
    assert p.query_tool_name == "query_web"


def test_provider_name_overrides_id():
    p = StubProvider(id="web", name="Research")
    assert p.name == "Research"
    assert p.query_tool_name == "query_web"  # tool name from id, not name


def test_query_tool_name_sanitized():
    p = StubProvider(id="Weird Id!!")
    assert p.query_tool_name == "query_weird_id"


# ---------------------------------------------------------------------------
# get_tools per mode
# ---------------------------------------------------------------------------


def test_default_mode_returns_query_tool():
    p = StubProvider(id="web", mode=ContextMode.default)
    tools = p.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_web"


def test_agent_mode_returns_single_query_tool():
    p = StubProvider(id="web", mode=ContextMode.agent)
    tools = p.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_web"


def test_tools_mode_returns_underlying_tools():
    p = StubProvider(id="web", mode=ContextMode.tools)
    tools = p.get_tools()
    # StubProvider doesn't override _all_tools, so it falls back to query_tool
    assert len(tools) == 1


# ---------------------------------------------------------------------------
# Instructions are mode-aware
# ---------------------------------------------------------------------------


def test_instructions_default_mode_mentions_query_tool():
    p = StubProvider(id="web")
    out = p.instructions()
    assert "query_web" in out


def test_instructions_tools_mode_differs():
    p_default = StubProvider(id="web", mode=ContextMode.default)
    p_tools = StubProvider(id="web", mode=ContextMode.tools)
    assert p_default.instructions() != p_tools.instructions()


# ---------------------------------------------------------------------------
# _query_tool wraps aquery + serializes Answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_tool_returns_json_payload():
    p = StubProvider(id="web", answer_text="hello")
    tool = p._query_tool()

    # The @tool decorator produces a Function whose entrypoint wraps our async
    # callable. Invoke directly through the underlying function attribute.
    entry = tool.entrypoint
    result = await entry(question="anything")
    payload = json.loads(result)
    assert payload["text"] == "hello"
    assert payload["results"] == [asdict(Document(id="1", name="doc"))]


class BrokenProvider(StubProvider):
    async def aquery(self, question: str) -> Answer:
        raise RuntimeError("backend exploded")


@pytest.mark.asyncio
async def test_query_tool_serializes_errors():
    p = BrokenProvider(id="web")
    tool = p._query_tool()
    result = await tool.entrypoint(question="anything")
    payload = json.loads(result)
    assert "error" in payload
    assert "RuntimeError" in payload["error"]
    assert "backend exploded" in payload["error"]
