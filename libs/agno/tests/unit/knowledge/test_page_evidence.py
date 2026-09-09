import asyncio
from types import SimpleNamespace

import pytest

from agno.knowledge.page import (
    PageChanged,
    PageError,
    PageNotFound,
    SearchHit,
    SearchResult,
    arender_page_evidence,
    render_page_evidence,
)


def hit(path="/a.md", revision="r1", content="retrieved excerpt", rank=1, **kwargs):
    return SearchHit(
        path=path,
        revision=revision,
        content=content,
        rank=rank,
        score=0.8,
        title=kwargs.get("title", "Title"),
        url="https://example.com" + path,
        chunk_id=str(rank),
    )


@pytest.fixture
def reader():
    state = SimpleNamespace(calls=[], contents={"/a.md": "Whole page"}, error=None)

    def read(path, **kwargs):
        state.calls.append((path, kwargs))
        if state.error:
            raise state.error
        content = state.contents.get(path, "Other whole page")
        return content if len(content) <= kwargs["max_chars"] else None

    async def aread(path, **kwargs):
        return read(path, **kwargs)

    return SimpleNamespace(read_full_page=read, aread_full_page=aread), state


async def render(reader, results, asynchronous, **kwargs):
    return (
        await arender_page_evidence(reader, results, **kwargs)
        if asynchronous
        else render_page_evidence(reader, results, **kwargs)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_rank_grouping_and_revision_pinned_single_read(reader, asynchronous):
    knowledge, state = reader
    result = await render(
        knowledge, SearchResult(results=(hit("/b.md", rank=3), hit(rank=2), hit(rank=1))), asynchronous
    )
    assert [p.path for p in result.pages] == ["/a.md", "/b.md"]
    assert len(state.calls) == 2 and all(args["revision"] == "r1" for _, args in state.calls)
    assert result.pages[0].content == "Whole page" and result.pages[0].coverage == "full"
    assert not result.truncated and not result.omitted_pages
    assert result.text.count("Whole page") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("error", [PageChanged(current_revision="r2"), PageNotFound(), PageError()])
async def test_failure_retains_retrieved_excerpts_never_substitutes_latest(reader, asynchronous, error):
    knowledge, state = reader
    state.error = error
    result = await render(knowledge, SearchResult(results=(hit(), hit(rank=2, content="second excerpt"))), asynchronous)
    assert result.pages[0].coverage == "excerpts"
    assert "retrieved excerpt" in result.text and "second excerpt" in result.text
    assert error.code in result.pages[0].warnings
    assert len(state.calls) == 1 and state.calls[0][1]["revision"] == "r1"


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_missing_and_mixed_revisions_are_not_blended(reader, asynchronous):
    knowledge, state = reader
    result = await render(
        knowledge,
        SearchResult(results=(hit(revision=""), hit(revision="r1", rank=2), hit(revision="r2", rank=3))),
        asynchronous,
    )
    assert [p.revision for p in result.pages] == ["", "r1", "r2"]
    assert result.pages[0].warnings == ("missing_revision",)
    assert [args["revision"] for _, args in state.calls] == ["r1", "r2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("budget", [0, 1, 150, 250, 500])
async def test_final_character_budget_includes_unicode_metadata_warnings_and_separators(reader, asynchronous, budget):
    knowledge, state = reader
    state.contents = {"/a.md": "🙂" * 9000}
    source = SearchResult(
        results=(hit(content="日本語" * 1000), hit("/b.md", rank=2)),
        partial=True,
        truncated=True,
        omitted_count=5,
        warnings=("search_unavailable",),
    )
    result = await render(knowledge, source, asynchronous, max_chars=budget)
    assert len(result.text) <= budget
    assert result.partial and result.truncated
    assert "search_unavailable" in result.warnings
    assert "search_omitted:5" in result.warnings
    if budget == 0:
        assert not state.calls and not result.text and result.omitted_pages == 2
    for page in result.pages:
        assert page.coverage != "full" or page.content == state.contents.get(page.path, "Other whole page")
    result.text.encode("utf-8", errors="strict")


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_custom_formatter_cannot_exceed_budget_or_break_its_delimiters(reader, asynchronous):
    knowledge, state = reader
    state.contents["/a.md"] = "x" * 200

    def formatter(page):
        return "<evidence>" + page.content * 2 + "</evidence>"

    result = await render(knowledge, SearchResult(results=(hit(),)), asynchronous, max_chars=100, formatter=formatter)
    assert len(result.text) <= 100
    assert result.text.startswith("<evidence>") and result.text.endswith("</evidence>")
    assert result.pages[0].coverage == "excerpts"
    omitted = await render(knowledge, SearchResult(results=(hit(),)), asynchronous, max_chars=5, formatter=formatter)
    assert not omitted.text and omitted.omitted_pages == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_attributes_are_escaped_and_expansion_deadline_stops_reads(reader, asynchronous, monkeypatch):
    knowledge, state = reader
    import agno.knowledge.page.evidence as module

    times = iter((0, 100))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times, 100))
    result = await render(knowledge, SearchResult(results=(hit(title='"/><evil>'),)), asynchronous, timeout=1)
    assert not state.calls
    assert "&quot;/&gt;&lt;evil&gt;" in result.text and "expansion_deadline" in result.text


@pytest.mark.asyncio
async def test_async_cancellation_propagates(reader):
    knowledge, _ = reader

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    knowledge.aread_full_page = cancelled
    with pytest.raises(asyncio.CancelledError):
        await arender_page_evidence(knowledge, SearchResult(results=(hit(),)))


@pytest.mark.parametrize("kwargs", [{"max_chars": -1}, {"max_chars": True}, {"timeout": 0}, {"timeout": float("nan")}])
def test_invalid_budgets_fail_before_io(reader, kwargs):
    knowledge, state = reader
    with pytest.raises(ValueError):
        render_page_evidence(knowledge, SearchResult(results=(hit(),)), **kwargs)
    assert not state.calls
