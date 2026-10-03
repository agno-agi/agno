"""Search pagination preserves every matching line without widening reply limits."""

from types import SimpleNamespace

import pytest

from agno.db.sqlite import SqliteDb
from agno.offload import ResultStore
from agno.offload.store import SEARCH_MAX_CHARS, SEARCH_MAX_MATCHES
from agno.offload.tools import get_search_result_function
from agno.run import RunContext


@pytest.fixture
def stored_result(tmp_path):
    store = ResultStore(db=SqliteDb(db_file=str(tmp_path / "results.db")))

    def save(content):
        ref = store.offload(
            session_id="session",
            user_id="alice",
            run_id="run",
            tool_call_id="call",
            tool_name="fetch_report",
            tool_args={},
            output=content,
        )
        return store, ref.result_id

    return save


@pytest.mark.parametrize("pattern", ["needle", r"needle-\d+"])
@pytest.mark.parametrize("context_lines", [0, 20])
@pytest.mark.asyncio
async def test_all_matching_lines_are_reachable_across_pages(stored_result, pattern, context_lines):
    # Sparse hits catch confusion between a match offset and a source line number.
    content = "\n".join(f"needle-{i} " + "x" * 480 if i % 2 else "other " + "x" * 480 for i in range(1, 106))
    store, result_id = stored_result(content)
    expected = list(range(1, 106, 2))
    seen = []
    start_line = 1
    while True:
        matches = store.search(result_id, pattern, context_lines, start_line=start_line)
        assert matches == await store.asearch(result_id, pattern, context_lines, start_line=start_line)
        assert 0 < len(matches) <= SEARCH_MAX_MATCHES
        assert sum(len(match.line) for match in matches) <= SEARCH_MAX_CHARS
        seen.extend(match.line_number for match in matches)
        if not matches[-1].more:
            break
        start_line = matches[-1].line_number + 1
    assert seen == expected


@pytest.mark.parametrize("pattern", ["needle", r"needle-\d+"])
@pytest.mark.asyncio
async def test_start_line_is_inclusive_and_context_can_precede_it(stored_result, pattern):
    store, result_id = stored_result("needle-1\nneedle-2\nneedle-3")
    matches = store.search(result_id, pattern, context_lines=1, start_line=3)
    assert matches == await store.asearch(result_id, pattern, context_lines=1, start_line=3)
    assert [match.line_number for match in matches] == [3]
    assert matches[0].line == "2: needle-2\n3: needle-3"
    assert matches[0].more is False
    assert store.search(result_id, pattern, start_line=4) == []
    assert await store.asearch(result_id, pattern, start_line=4) == []


@pytest.mark.parametrize("start_line", [0, -1])
@pytest.mark.asyncio
async def test_invalid_start_line_is_rejected(stored_result, start_line):
    store, result_id = stored_result("needle")
    with pytest.raises(ValueError, match="start_line must be at least 1"):
        store.search(result_id, "needle", start_line=start_line)
    with pytest.raises(ValueError, match="start_line must be at least 1"):
        await store.asearch(result_id, "needle", start_line=start_line)


def test_subprocess_does_not_evaluate_lines_before_start(stored_result, monkeypatch):
    from agno.offload import store as store_module

    monkeypatch.setattr(store_module, "SEARCH_TIMEOUT_SECONDS", 1.5)
    store, result_id = stored_result("a" * 40_000 + "b\naaa")
    matches = store.search(result_id, r"(a+)+$", start_line=2)
    assert [match.line_number for match in matches] == [2]


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("line_count", [20, 21])
@pytest.mark.asyncio
async def test_tool_exposes_accurate_continuation(stored_result, async_mode, line_count):
    store, result_id = stored_result("\n".join("needle" for _ in range(line_count)))
    tool = get_search_result_function(
        SimpleNamespace(_result_store=store),
        RunContext(run_id="run", session_id="session", user_id="alice"),
        async_mode=async_mode,
    )
    assert tool.entrypoint is not None
    assert "start_line" in tool.parameters["properties"]
    assert "start_line" not in tool.parameters.get("required", [])
    reply = tool.entrypoint(result_id=result_id, pattern="needle")
    if async_mode:
        reply = await reply
    if line_count == 20:
        assert "20 match(es)" in reply
        assert "more follow" not in reply
    else:
        assert "start_line=21" in reply
        following = tool.entrypoint(result_id=result_id, pattern="needle", start_line=21)
        if async_mode:
            following = await following
        assert "1 match(es)" in following
        assert "21: needle" in following
        assert "more follow" not in following


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize(
    "context", [{"session_id": "other", "user_id": "alice"}, {"session_id": "session", "user_id": "bob"}]
)
@pytest.mark.asyncio
async def test_pagination_cannot_read_another_session_or_user(stored_result, async_mode, context):
    store, result_id = stored_result("needle\nneedle")
    tool = get_search_result_function(
        SimpleNamespace(_result_store=store), RunContext(run_id="run", **context), async_mode=async_mode
    )
    assert tool.entrypoint is not None
    reply = tool.entrypoint(result_id=result_id, pattern="needle", start_line=2)
    if async_mode:
        reply = await reply
    assert reply.startswith("Error: result")
    assert "belongs to a different" in reply


def test_tool_reports_invalid_start_line(stored_result):
    store, result_id = stored_result("needle")
    tool = get_search_result_function(
        SimpleNamespace(_result_store=store), RunContext(run_id="run", session_id="session", user_id="alice")
    )
    assert tool.entrypoint is not None
    assert "start_line must be at least 1" in tool.entrypoint(result_id=result_id, pattern="needle", start_line=0)
