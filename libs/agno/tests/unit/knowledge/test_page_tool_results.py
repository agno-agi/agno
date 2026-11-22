import json
from types import SimpleNamespace

import pytest
from fastmcp import Client

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import (
    GrepMatch,
    GrepResult,
    Page,
    PageCommandResult,
    PageError,
    PageFileSystem,
    PageList,
    PageNotFound,
    SearchHit,
    SearchResult,
)
from agno.knowledge.page._commands import run_command, run_command_result
from agno.os import AgentOS
from agno.os.config import MCPConfig
from agno.os.mcp import build_mcp_server
from agno.run.agent import RunOutput


@pytest.mark.parametrize(
    "command", ["not-a-tool x", "cat /missing", "cat /a /missing", "wc /missing", 'rg "[" /', "cat /a | head"]
)
def test_typed_command_errors_preserve_legacy_text(command):
    corpus = {"/a.md": "Actual document saying: page_unavailable and invalid_command."}
    result = run_command_result(command, corpus)
    assert result.is_error and result.errors
    assert result.text == run_command(command, corpus)


def test_document_words_are_never_error_signals():
    result = run_command_result("cat /a", {"/a.md": "parse error: no such file. page_unavailable invalid_command"})
    assert not result.is_error and not result.errors


def test_final_json_byte_bound_handles_unicode_and_invalidates_old_continuation():
    original = PageCommandResult(text='🙂\\"\n' * 1000, continuation="tail -n +100 /a.md")
    result = original.bounded(1024)
    assert len(result.model_dump_json().encode("utf-8")) <= 1024
    assert result.truncated and result.continuation is None
    assert original.text.startswith(result.text)
    with pytest.raises(ValueError):
        original.bounded(10)


@pytest.fixture
def corpus():
    page = Page(
        content_id="a",
        namespace="n",
        path="/a.md",
        url="https://example.com/a",
        title="A",
        revision="r1",
        digest="d",
        index_fingerprint="i",
        filesystem_version=1,
        expected_chunk_count=1,
    )
    state = SimpleNamespace(content="page_unavailable is a literal example", error=None)

    def listing(**kwargs):
        return PageList(pages=(page,))

    def read(path, **kwargs):
        if path != "/a.md":
            raise PageNotFound()
        if state.error:
            raise state.error
        assert kwargs.get("revision") in (None, "r1")
        return SimpleNamespace(text=state.content, next_offset=None, revision="r1")

    return PageFileSystem(knowledge=SimpleNamespace(list_pages=listing, read_page=read)), state


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_command_direct_outcome_storage_error_and_byte_bound(corpus, asynchronous):
    files, state = corpus
    state.content = "🙂" * 2000
    result = (
        await files.arun_command_result("cat /a", max_output_bytes=1024)
        if asynchronous
        else files.run_command_result("cat /a", max_output_bytes=1024)
    )
    assert result.truncated and not result.is_error and len(result.model_dump_json().encode()) <= 1024
    state.error = PageError()
    result = await files.arun_command_result("cat /a") if asynchronous else files.run_command_result("cat /a")
    assert result.is_error and result.errors == ("page_unavailable",)


def test_literal_grep_reports_incomplete_without_text_inference():
    page = SimpleNamespace(path="/a.md")
    knowledge = SimpleNamespace(
        list_pages=lambda **kw: PageList.model_construct(pages=(page,)),
        grep_pages=lambda *a, **kw: GrepResult(
            matches=(GrepMatch(path="/a.md", url="https://example.com/a", revision="r1", line_number=1, text="x"),),
            complete=False,
            stop_reason="deadline",
        ),
    )
    result = PageFileSystem(knowledge=knowledge).run_command_result("rg x /")
    assert result.partial and result.stop_reason == "deadline" and not result.is_error


@pytest.mark.asyncio
async def test_native_mcp_command_schema_and_error_status(corpus):
    files, _ = corpus
    toolkit = files.tools(transport="mcp", tool_name="read_docs", description="Product-owned docs command")
    server = build_mcp_server(AgentOS(agents=[Agent(id="docs")], mcp=MCPConfig(default_tools=False, tools=[toolkit])))
    async with Client(server) as client:
        tools = await client.list_tools()
        assert len(tools) == 1 and tools[0].name == "read_docs"
        assert tools[0].output_schema and tools[0].annotations.read_only_hint
        result = await client.call_tool("read_docs", {"command": "cat /a"})
        assert result.structured_content["is_error"] is False
        assert "page_unavailable" in result.structured_content["text"]
        failed = await client.call_tool("read_docs", {"command": "cat /missing"}, raise_on_error=False)
        assert failed.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_search_factory_parity_schema_references_and_failure(monkeypatch, asynchronous):
    knowledge = Knowledge()
    knowledge.page_store = object()
    hit = SearchHit(
        path="/a.md",
        url="https://example.com/a",
        title="A",
        revision="r1",
        chunk_id="c",
        content="Excerpt",
        score=0.8,
        rank=1,
    )
    result = SearchResult(results=(hit,), partial=True, warnings=("alternative_unavailable",))
    calls = []

    def search(query, **kwargs):
        calls.append((query, kwargs))
        if query == "fail":
            raise PageError()
        return result

    async def asearch(query, **kwargs):
        return search(query, **kwargs)

    monkeypatch.setattr(knowledge, "search_pages", search)
    monkeypatch.setattr(knowledge, "asearch_pages", asearch)
    response = RunOutput()
    chat = knowledge.get_tools(
        page_results=True, tool_name="search_docs", run_response=response, async_mode=asynchronous
    )[0]
    value = (
        await chat.entrypoint("question", ["alternate"]) if asynchronous else chat.entrypoint("question", ["alternate"])
    )
    assert json.loads(value) == result.model_dump(mode="json")
    assert response.references[0].query == "question" and response.references[0].references
    mcp = knowledge.get_tools(page_results=True, tool_name="search_docs", transport="mcp", async_mode=asynchronous)[0]
    server = build_mcp_server(AgentOS(agents=[Agent(id="docs")], mcp=MCPConfig(default_tools=False, tools=[mcp])))
    async with Client(server) as client:
        listed = await client.list_tools()
        assert listed[0].output_schema and listed[0].name == "search_docs"
        value = await client.call_tool("search_docs", {"query": "question", "alternatives": ["alternate"]})
        assert value.structured_content == result.model_dump(mode="json")
        failed = await client.call_tool("search_docs", {"query": "fail"}, raise_on_error=False)
        assert failed.is_error
    assert calls[0][1] == {"alternatives": ["alternate"], "max_output_bytes": 32000}
