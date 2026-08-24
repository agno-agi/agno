"""Unit tests for result offloading: thresholds, envelopes, caps, access."""

import json
import os
import tempfile
import time

import pytest

from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.errors import QuotaExceededError
from agno.offload import ResultStore, result_id_for
from agno.offload.store import (
    NEVER_OFFLOADED_TOOLS,
    READ_MAX_CHARS,
    SWEEP_INTERVAL_SECONDS,
    render_refused_envelope,
    render_stored_envelope,
)


@pytest.fixture
def store(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "offload.db"))
    fs = FileSystem(backend=db, namespace="tool-results")
    return ResultStore(db=db, fs=fs, threshold_chars=100)


def _offload(store, output, *, session_id="S1", run_id="r1", tool_call_id="tc1", tool_name="fetch_page", **kwargs):
    return store.offload(
        session_id=session_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_args={},
        output=output,
        **kwargs,
    )


# ------------------------------------------------------------------
# Threshold
# ------------------------------------------------------------------


def test_exactly_threshold_stays_inline(store):
    assert store.should_offload("fetch_page", "x" * 100) is False


def test_threshold_plus_one_offloads(store):
    assert store.should_offload("fetch_page", "x" * 101) is True


def test_default_threshold_matches_one_read_result_page():
    db = SqliteDb(db_file=os.path.join(tempfile.mkdtemp(), "d.db"))
    default_store = ResultStore(db=db, fs=FileSystem(backend=db, namespace="tool-results"))
    assert default_store.threshold_chars == 16000 == READ_MAX_CHARS
    assert default_store.should_offload("t", "x" * 16000) is False
    assert default_store.should_offload("t", "x" * 16001) is True


def test_non_string_output_is_measured_as_text(store):
    assert store.should_offload("t", list(range(200))) is True
    assert store.should_offload("t", 42) is False


# ------------------------------------------------------------------
# The never-offloaded set
# ------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", NEVER_OFFLOADED_TOOLS)
def test_read_back_tools_own_output_is_never_offloaded(store, tool_name):
    assert store.should_offload(tool_name, "x" * 100_000) is False


def test_sub_threshold_result_is_never_offloaded(store):
    assert store.should_offload("fetch_page", "short") is False


# ------------------------------------------------------------------
# Envelope shapes
# ------------------------------------------------------------------


def test_stored_envelope_shape(store):
    payload = "\n".join(f"line {i}" for i in range(1, 8413))
    ref = _offload(store, payload)
    envelope = render_stored_envelope(ref, "line 1\nline 2")
    assert envelope.startswith(f'<result id="{ref.result_id}" tool="fetch_page" lines="8412" size=')
    assert "line 1\nline 2\n</result>" in envelope
    assert f'read_result("{ref.result_id}")' in envelope
    assert f'search_result("{ref.result_id}", pattern)' in envelope


def test_refused_envelope_carries_head_and_tail(store):
    payload = "\n".join(f"line {i}" for i in range(1, 101))
    envelope = render_refused_envelope(
        tool_name="fetch_page",
        output=payload,
        reason="session storage is full (204800000 of 200000000 bytes)",
        preview_lines=20,
        preview_chars=1200,
    )
    assert 'stored="false"' in envelope
    assert 'reason="session storage is full (204800000 of 200000000 bytes)"' in envelope
    assert "line 1\n" in envelope
    assert "[... 75 lines omitted ...]" in envelope
    assert "line 100" in envelope
    assert envelope.endswith("Full result was NOT stored. Re-run the tool with a narrower query if you need the rest.")


def test_refused_envelope_omits_marker_when_everything_fits(store):
    payload = "\n".join(f"line {i}" for i in range(1, 6))
    envelope = render_refused_envelope(
        tool_name="t", output=payload, reason="boom", preview_lines=20, preview_chars=1200
    )
    assert "lines omitted" not in envelope
    assert "line 5" in envelope


def test_preview_honours_lines_then_chars():
    from agno.offload.store import _head_preview

    # The head of a preview: lines first, then characters.
    assert _head_preview("a\nb\nc\nd\ne", preview_lines=3, preview_chars=10_000) == "a\nb\nc"
    assert _head_preview("a\nb\nc\nd\ne", preview_lines=100, preview_chars=3) == "a\nb"


def test_multibyte_content_reports_bytes_not_characters(store):
    payload = "é" * 1000
    ref = _offload(store, payload)
    assert ref.size_bytes == 2000
    assert len(payload) == 1000


def test_line_count_matches_the_payload(store):
    payload = "a\nb\nc"
    ref = _offload(store, payload)
    assert ref.line_count == 3


def test_json_output_gets_the_json_content_type(store):
    ref = _offload(store, json.dumps({"k": ["v"] * 100}))
    assert ref.content_type == "json"
    assert ref.path.endswith(".json")


def test_text_output_gets_the_text_content_type(store):
    ref = _offload(store, "plain " * 100)
    assert ref.content_type == "text"
    assert ref.path.endswith(".txt")


# ------------------------------------------------------------------
# Ids and paths
# ------------------------------------------------------------------


def test_result_id_is_deterministic_and_short():
    first = result_id_for("S1", "run-1", "call-1")
    assert first == result_id_for("S1", "run-1", "call-1")
    assert first != result_id_for("S1", "run-1", "call-2")
    assert first != result_id_for("S2", "run-1", "call-1")
    assert first.startswith("res_")
    assert len(first) == 14


def test_team_member_results_land_under_shared(store):
    ref = _offload(store, "x" * 500, shared=True)
    assert ref.path.startswith("shared/")
    ref2 = _offload(store, "x" * 500, tool_call_id="tc2")
    assert ref2.path.startswith("results/")


# ------------------------------------------------------------------
# Read caps
# ------------------------------------------------------------------


def test_read_clips_at_400_lines_and_reports_next_start_line(store):
    payload = "\n".join(f"line {i}" for i in range(1, 1001))
    ref = _offload(store, payload)
    page = store.read(ref.result_id)
    assert page.start_line == 1
    assert page.end_line == 400
    assert page.truncated is True
    assert page.next_start_line == 401
    assert page.line_count == 1000
    assert page.text.splitlines()[-1] == "line 400"


def test_read_clips_at_16000_chars(store):
    payload = "\n".join("x" * 200 for _ in range(300))
    ref = _offload(store, payload)
    page = store.read(ref.result_id)
    assert len(page.text) <= 16_000
    assert page.truncated is True
    assert page.next_start_line is not None


def test_read_of_the_final_page_reports_no_next_line(store):
    payload = "\n".join(f"line {i}" for i in range(1, 11))
    ref = _offload(store, payload)
    page = store.read(ref.result_id, start_line=5)
    assert page.end_line == 10
    assert page.next_start_line is None
    assert page.truncated is False


def test_read_range_is_inclusive(store):
    payload = "\n".join(f"line {i}" for i in range(1, 11))
    ref = _offload(store, payload)
    page = store.read(ref.result_id, start_line=2, end_line=4)
    assert page.text == "line 2\nline 3\nline 4"


def test_round_trip_returns_the_exact_original_bytes(store):
    payload = "unicode é ü 😀\nsecond line\n\ttabbed\n" * 200
    ref = _offload(store, payload)
    page = store.read(ref.result_id, 1, ref.line_count)
    # The page cap bounds one read; the payload file itself is byte-exact.
    stored = store._read_payload(store.get_row(ref.result_id))
    assert stored == payload
    assert page.text.startswith("unicode é ü 😀")


# ------------------------------------------------------------------
# Search caps
# ------------------------------------------------------------------


def test_search_stops_at_20_matches(store):
    payload = "\n".join("needle here" for _ in range(100))
    ref = _offload(store, payload)
    assert len(store.search(ref.result_id, "needle")) == 20


def test_search_clips_each_line_to_the_window(store):
    payload = "needle " + "x" * 2000
    ref = _offload(store, payload)
    match = store.search(ref.result_id, "needle")[0]
    assert len(match.line) <= 500 and len(match.line) >= 490
    assert match.line_number == 1


def test_search_with_context_lines(store):
    payload = "a\nb\nneedle\nd\ne"
    ref = _offload(store, payload)
    match = store.search(ref.result_id, "needle", context_lines=1)[0]
    # Every row in the block carries its own line number, so the match line is unambiguous.
    assert match.line == "2: b\n3: needle\n4: d"
    assert match.line_number == 3


def test_search_reports_1_indexed_line_numbers(store):
    payload = "a\nb\nneedle"
    ref = _offload(store, payload)
    assert store.search(ref.result_id, "needle")[0].line_number == 3


# ------------------------------------------------------------------
# Failure is loud, never silent
# ------------------------------------------------------------------


def test_quota_refusal_produces_the_head_tail_envelope_and_does_not_raise(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "quota.db"))
    fs = FileSystem(backend=db, namespace="tool-results")
    store = ResultStore(db=db, fs=fs, threshold_chars=10)
    payload = "\n".join(f"line {i}" for i in range(1, 501))

    # Force the write to be refused the way a full namespace does.
    def refuse(*args, **kwargs):
        raise QuotaExceededError("full", scope="namespace", current=204_800_000, limit=200_000_000)

    store._session_fs = lambda session_id: type("FS", (), {"namespace": "ns", "write": staticmethod(refuse)})()
    envelope = store.offload_for_model(
        session_id="S1", run_id="r1", tool_call_id="tc1", tool_name="fetch_page", tool_args={}, output=payload
    )
    assert 'stored="false"' in envelope
    assert "session storage is full (204800000 of 200000000 bytes)" in envelope
    assert "lines omitted" in envelope
    assert "line 500" in envelope


def test_backend_error_produces_a_refused_envelope_and_does_not_raise(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "err.db"))
    fs = FileSystem(backend=db, namespace="tool-results")
    store = ResultStore(db=db, fs=fs, threshold_chars=10)

    def boom(*args, **kwargs):
        raise RuntimeError("backend down")

    store.offload = boom
    envelope = store.offload_for_model(
        session_id="S1", run_id="r1", tool_call_id="tc1", tool_name="t", tool_args={}, output="x" * 500
    )
    assert 'stored="false"' in envelope
    assert "backend down" in envelope


def test_index_write_failure_does_not_leave_an_orphan_payload(store, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("index down")

    monkeypatch.setattr(store, "_db_call", boom)
    with pytest.raises(RuntimeError):
        _offload(store, "x" * 500)
    session_fs = store._session_fs("S1")
    assert session_fs.list("") == []


# ------------------------------------------------------------------
# Listing, cleanup, sweep
# ------------------------------------------------------------------


def test_live_ids_are_newest_first_and_capped(store, monkeypatch):
    # created_at has one-second resolution, so distinct timestamps are forced:
    # on equal values a reverse-sorted assertion could not catch an
    # oldest-first regression.
    import itertools

    from agno.offload import store as store_module

    base = 1_700_000_000
    tick = itertools.count()
    monkeypatch.setattr(store_module.time, "time", lambda: base + next(tick))
    for i in range(25):
        store.offload(
            session_id="S1",
            run_id="r1",
            tool_call_id=f"tc{i}",
            tool_name=f"tool{i}",
            tool_args={},
            output="x" * 500,
        )
    refs = store.live_ids("S1")
    assert len(refs) == 20
    created = [ref.created_at for ref in refs]
    assert all(earlier > later for earlier, later in zip(created, created[1:]))
    assert [ref.tool_name for ref in refs] == [f"tool{i}" for i in range(24, 4, -1)]


def test_live_ids_scope_to_one_session(store):
    _offload(store, "x" * 500, session_id="S1")
    _offload(store, "x" * 500, session_id="S2", tool_call_id="tc2")
    assert len(store.live_ids("S1")) == 1
    assert len(store.live_ids("S2")) == 1


def test_live_ids_limit_is_respected(store):
    for i in range(5):
        _offload(store, "x" * 500, tool_call_id=f"tc{i}")
    assert len(store.live_ids("S1", limit=2)) == 2


def test_delete_for_sessions_removes_rows_and_payloads(store):
    ref = _offload(store, "x" * 500)
    session_fs = store._session_fs("S1")
    assert session_fs.read(ref.path) is not None
    assert store.delete_for_sessions(["S1"]) == 1
    assert store.get_row(ref.result_id) is None
    assert session_fs.read(ref.path) is None


def test_sweep_deletes_only_expired_rows(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "ttl.db"))
    fs = FileSystem(backend=db, namespace="tool-results")
    expiring = ResultStore(db=db, fs=fs, threshold_chars=10, ttl_seconds=60)
    forever = ResultStore(db=db, fs=fs, threshold_chars=10, ttl_seconds=None)
    ref_expiring = expiring.offload(
        session_id="S", run_id="r", tool_call_id="t1", tool_name="x", tool_args={}, output="a" * 100
    )
    ref_forever = forever.offload(
        session_id="S", run_id="r", tool_call_id="t2", tool_name="x", tool_args={}, output="b" * 100
    )
    assert expiring.sweep_expired(now=int(time.time())) == 0
    assert expiring.sweep_expired(now=int(time.time()) + 120) == 1
    assert expiring.get_row(ref_expiring.result_id) is None
    assert forever.get_row(ref_forever.result_id) is not None


def test_maybe_sweep_is_a_noop_without_ttl(tmp_path, monkeypatch):
    db = SqliteDb(db_file=str(tmp_path / "nottl.db"))
    store = ResultStore(db=db, fs=FileSystem(backend=db, namespace="tool-results"))
    calls = []
    monkeypatch.setattr(store, "sweep_expired", lambda now=None: calls.append(1) or 0)
    store.maybe_sweep()
    assert calls == []


# ------------------------------------------------------------------
# Errors
# ------------------------------------------------------------------


def test_read_of_unknown_id_raises_key_error(store):
    with pytest.raises(KeyError):
        store.read("res_deadbeef00")


def test_search_of_unknown_id_raises_key_error(store):
    with pytest.raises(KeyError):
        store.search("res_deadbeef00", "x")


# ------------------------------------------------------------------
# Namespace per session
# ------------------------------------------------------------------
def test_two_session_ids_that_normalise_alike_stay_separate(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "ns.db"))
    store = ResultStore(db=db, fs=FileSystem(backend=db, namespace="tool-results"), threshold_chars=10)
    upper = store.offload(
        session_id="Alpha", run_id="R1", tool_call_id="c1", tool_name="fetch", tool_args={}, output="A" * 200
    )
    lower = store.offload(
        session_id="alpha", run_id="R1", tool_call_id="c1", tool_name="fetch", tool_args={}, output="b" * 200
    )
    assert upper.result_id != lower.result_id
    assert store.get_row(upper.result_id)["namespace"] != store.get_row(lower.result_id)["namespace"]

    # Deleting one session's payloads must leave the other's readable.
    store.delete_for_sessions(["alpha"])
    assert store.read(upper.result_id).text.startswith("A")
    assert store.get_row(lower.result_id) is None


def test_two_sessions_that_reuse_a_run_id_keep_separate_results(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "runid.db"))
    store = ResultStore(db=db, fs=FileSystem(backend=db, namespace="tool-results"), threshold_chars=10)
    first = store.offload(
        session_id="S1", run_id="shared-run", tool_call_id="c1", tool_name="fetch", tool_args={}, output="one" * 100
    )
    second = store.offload(
        session_id="S2", run_id="shared-run", tool_call_id="c1", tool_name="fetch", tool_args={}, output="two" * 100
    )
    assert first.result_id != second.result_id
    assert store.read(first.result_id).text.startswith("one")
    assert store.read(second.result_id).text.startswith("two")


def test_namespace_for_is_canonical_and_within_the_segment_limit():
    from agno.fs._paths import MAX_SEGMENT_CHARS, normalize_namespace
    from agno.offload.store import namespace_for

    for session_id in ["plain", "my session", "sesi\u00f3n-\u00fc", "MiXeD:Case/Id", "{tenant}", "s" * 500, ""]:
        namespace = namespace_for(session_id)
        assert normalize_namespace(namespace) == namespace, session_id
        assert all(len(segment) <= MAX_SEGMENT_CHARS for segment in namespace.split("/")), session_id
    assert namespace_for("Alpha") != namespace_for("alpha")
    assert namespace_for("a b") != namespace_for("a-b")


def test_maybe_sweep_runs_at_most_once_per_interval(tmp_path, monkeypatch):
    db = SqliteDb(db_file=str(tmp_path / "once.db"))
    store = ResultStore(db=db, fs=FileSystem(backend=db, namespace="tool-results"), ttl_seconds=60)
    calls = []
    monkeypatch.setattr(store, "sweep_expired", lambda now=None: calls.append(1) or 0)
    store.maybe_sweep()
    store.maybe_sweep()
    assert len(calls) == 1
    store._last_sweep_at -= SWEEP_INTERVAL_SECONDS
    store.maybe_sweep()
    assert len(calls) == 2


def test_offloading_runs_the_sweep(tmp_path, monkeypatch):
    db = SqliteDb(db_file=str(tmp_path / "sweeponwrite.db"))
    store = ResultStore(db=db, fs=FileSystem(backend=db, namespace="tool-results"), ttl_seconds=60, threshold_chars=10)
    calls = []
    monkeypatch.setattr(store, "sweep_expired", lambda now=None: calls.append(1) or 0)
    store.offload_for_model(
        session_id="S1",
        run_id="R1",
        tool_call_id="call-1",
        tool_name="fetch",
        tool_args={},
        output="x" * 200,
    )
    assert len(calls) == 1


def test_two_tool_call_ids_that_sanitise_alike_do_not_share_a_path(store):
    first = store.offload(
        session_id="S1", run_id="R1", tool_call_id="call/1", tool_name="fetch", tool_args={}, output="a" * 200
    )
    second = store.offload(
        session_id="S1", run_id="R1", tool_call_id="call_1", tool_name="fetch", tool_args={}, output="b" * 200
    )
    assert first.result_id != second.result_id
    assert first.path != second.path
    assert store.read(first.result_id).text.startswith("a")
    assert store.read(second.result_id).text.startswith("b")


def test_search_context_lines_are_clamped(store):
    ref = _offload(store, "\n".join(f"line {i}" for i in range(1, 201)))
    match = store.search(ref.result_id, r"^line 100$", context_lines=1000)[0]
    from agno.offload.store import SEARCH_MAX_CONTEXT_LINES

    assert len(match.line.split("\n")) == 2 * SEARCH_MAX_CONTEXT_LINES + 1
    assert match.line.startswith(f"{100 - SEARCH_MAX_CONTEXT_LINES}: ")


# ------------------------------------------------------------------
# Every character is recoverable, whatever the line shape
# ------------------------------------------------------------------
def _read_everything(store, result_id) -> str:
    out, line, char = [], 1, 0
    while line is not None:
        page = store.read(result_id, start_line=line, start_char=char)
        out.append(page.text)
        # A continuation inside a line glues without a newline; a new line gets one.
        if page.next_start_line is not None and not page.next_start_char:
            out.append("\n")
        line, char = page.next_start_line, page.next_start_char
    return "".join(out)


def test_a_single_long_line_is_recoverable_in_pieces(store):
    payload = json.dumps({"items": [{"i": i, "v": "x" * 30} for i in range(3000)]})
    assert "\n" not in payload and len(payload) > 3 * READ_MAX_CHARS
    ref = _offload(store, payload)
    first = store.read(ref.result_id)
    assert first.truncated is True
    assert first.next_start_line == 1 and first.next_start_char == READ_MAX_CHARS
    assert _read_everything(store, ref.result_id) == payload


def test_a_long_value_inside_pretty_json_loses_nothing(store):
    payload = json.dumps({"short": 1, "long": "y" * 30_000, "after": 2}, indent=2)
    ref = _offload(store, payload)
    assert _read_everything(store, ref.result_id) == payload


def test_a_page_boundary_never_drops_the_tail_of_a_line(store):
    payload = "\n".join(f"{i:05d} " + "z" * 194 for i in range(1, 501))  # 200-char lines
    ref = _offload(store, payload)
    assert _read_everything(store, ref.result_id) == payload


def test_end_line_below_start_line_is_an_empty_page_with_no_self_reference(store):
    ref = _offload(store, "\n".join(f"line {i}" for i in range(1, 50)))
    page = store.read(ref.result_id, start_line=1, end_line=0)
    assert page.text == "line 1"
    assert page.next_start_line == 2


def test_search_shows_a_window_around_a_match_on_a_long_line(store):
    payload = "a" * 20_000 + "FINDME_AT_END" + "b" * 100
    ref = _offload(store, payload)
    match = store.search(ref.result_id, "FINDME_AT_END")[0]
    assert "FINDME_AT_END" in match.line
    assert match.char_offset == 20_000
    assert len(match.line) <= 500
    assert match.line.startswith("...")


def test_a_refused_envelope_stays_small_for_a_huge_last_line(store):
    output = "\n".join(["header"] * 30 + ["x" * 2_000_000])
    envelope = render_refused_envelope(
        tool_name="t", output=output, reason="quota", preview_lines=20, preview_chars=1200
    )
    assert len(envelope) < 5_000
    assert 'stored="false"' in envelope


def test_sweep_deletes_index_rows_in_bounded_batches(tmp_path, monkeypatch):
    db = SqliteDb(db_file=str(tmp_path / "many.db"))
    store = ResultStore(db=db, threshold_chars=10, ttl_seconds=1)
    count = 1_007
    for i in range(count):
        store.offload(
            session_id="S", run_id="r", tool_call_id=f"c{i}", tool_name="t", tool_args={}, output="payload text"
        )
    # One bound parameter per id: a delete that binds every id at once fails
    # past SQLite's limit, so each statement must stay within a batch.
    sizes = []
    real_delete = db.delete_tool_results

    def counting_delete(result_ids):
        sizes.append(len(result_ids))
        return real_delete(result_ids)

    monkeypatch.setattr(db, "delete_tool_results", counting_delete)
    assert store.sweep_expired(now=int(time.time()) + 10) == count
    assert sum(sizes) == count
    assert max(sizes) <= 500
    assert store.live_ids("S") == []


def test_search_reports_when_the_budget_stopped_the_scan(store):
    payload = "\n".join(f"entry {i}: " + "w" * 480 for i in range(1, 301))
    ref = _offload(store, payload)
    matches = store.search(ref.result_id, r"^entry")
    assert len(matches) < 300
    assert matches[-1].more is True
    few = store.search(ref.result_id, r"^entry 1: ")
    assert few and few[-1].more is False


def test_clip_window_always_contains_the_match(store):
    from agno.offload.store import _clip_around

    for offset in (0, 1, 100, 124, 125, 126, 400, 499, 500, 1000, 1999):
        line = "x" * offset + "NEEDLE" + "y" * (2000 - offset)
        window = _clip_around(line, offset, len("NEEDLE"))
        assert "NEEDLE" in window, offset
        assert len(window) <= 500


def test_clip_window_keeps_a_long_match_whole_when_it_fits():
    from agno.offload.store import _clip_around

    match = "M" * 400
    line = "x" * 1000 + match + "y" * 1000
    window = _clip_around(line, 1000, len(match))
    assert match in window
    assert len(window) <= 500


# ------------------------------------------------------------------
# The scan deadline: a pattern that backtracks cannot hang the run
# ------------------------------------------------------------------


def test_catastrophic_pattern_is_killed_at_the_deadline(store, monkeypatch):
    from agno.offload import store as store_module

    monkeypatch.setattr(store_module, "SEARCH_TIMEOUT_SECONDS", 1.5)
    ref = _offload(store, "a" * 40_000 + "b")
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="did not finish"):
        store.search(ref.result_id, r"(a+)+$")
    assert time.monotonic() - started < 30


@pytest.mark.asyncio
async def test_catastrophic_pattern_is_killed_on_the_async_path(store, monkeypatch):
    from agno.offload import store as store_module

    monkeypatch.setattr(store_module, "SEARCH_TIMEOUT_SECONDS", 1.5)
    ref = _offload(store, "a" * 40_000 + "b")
    with pytest.raises(TimeoutError, match="did not finish"):
        await store.asearch(ref.result_id, r"(a+)+$")


def test_a_repeating_pattern_that_finishes_still_matches(store):
    # The subprocess path returns real matches, not only timeouts.
    ref = _offload(store, "x" * 200 + "\n" + "needle-42" + "\n" + "x" * 200)
    matches = store.search(ref.result_id, r"needle-\d+")
    assert [m.line_number for m in matches] == [2]
    assert "needle-42" in matches[0].line


def test_a_plain_pattern_stays_in_process(store, monkeypatch):
    # A pattern with no repetition cannot backtrack and must not pay for a
    # subprocess: with the spawn path stubbed out, the scan still answers.
    from agno.offload import store as store_module

    def _boom(*args, **kwargs):
        raise AssertionError("plain patterns must not use the subprocess scan")

    monkeypatch.setattr(store_module, "_scan_in_subprocess", _boom)
    ref = _offload(store, "alpha\nbeta needle gamma\n" + "x" * 200)
    matches = store.search(ref.result_id, "needle")
    assert [m.line_number for m in matches] == [2]


def test_search_never_reexecutes_a_guardless_caller_script(tmp_path):
    # The scan child must be a bare interpreter: a multiprocessing spawn
    # worker re-imports the parent's __main__, so a user script without an
    # import guard would run twice - duplicate side effects included.
    import subprocess
    import sys

    sentinel = tmp_path / "executions.log"
    script = tmp_path / "guardless.py"
    script.write_text(
        "import os, sys\n"
        f"open({str(sentinel)!r}, 'a').write('ran\\n')\n"
        "sys.path.insert(0, os.environ['AGNO_PATH'])\n"
        "from agno.db.sqlite import SqliteDb\n"
        "from agno.fs import FileSystem\n"
        "from agno.offload.store import ResultStore\n"
        f"db = SqliteDb(db_file=os.path.join({str(tmp_path)!r}, 'g.db'))\n"
        "store = ResultStore(db=db, fs=FileSystem(backend=db, namespace='tool-results'), threshold_chars=10)\n"
        "ref = store.offload(session_id='s', run_id='r', tool_call_id='c', tool_name='t', tool_args={}, output='alpha\\nneedle-42\\nomega')\n"
        "matches = store.search(ref.result_id, r'needle-\\d+')\n"
        "print('MATCHES', len(matches))\n"
    )
    import os

    env = dict(os.environ, AGNO_PATH=str(next(p for p in sys.path if p.endswith("libs/agno"))))
    completed = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120, env=env)
    assert completed.returncode == 0, completed.stderr
    assert "MATCHES 1" in completed.stdout
    assert sentinel.read_text() == "ran\n", "the caller script was executed more than once"


# ------------------------------------------------------------------
# The envelope previews the tail as well as the head
# ------------------------------------------------------------------


def test_envelope_preview_carries_head_and_tail(store):
    output = "\n".join(f"row {i}: value={i * 7}" for i in range(1, 501))
    envelope = store.offload_for_model(
        session_id="S1", run_id="r1", tool_call_id="tail-1", tool_name="fetch", tool_args={}, output=output
    )
    assert "row 1: value=7" in envelope
    assert "row 500: value=3500" in envelope
    assert "lines omitted ...]" in envelope
    # The stored row carries the same block, so a replayed envelope shows the
    # tail too, not only the head.
    rows = [r for r in store.db.get_tool_results_for_session("S1") if r["tool_call_id"] == "tail-1"]
    assert "row 500: value=3500" in rows[0]["preview"]


def test_short_output_previews_whole_with_no_tail_marker(store):
    envelope = store.offload_for_model(
        session_id="S1", run_id="r1", tool_call_id="tail-2", tool_name="fetch", tool_args={}, output="x" * 150
    )
    assert "lines omitted" not in envelope


def test_envelope_previews_a_tail_even_for_one_huge_line(store):
    # A single very long line - the common oversized JSON tool result - is
    # cut by the character cap, not by lines, and still shows a tail.
    envelope = store.offload_for_model(
        session_id="S1", run_id="r1", tool_call_id="huge-1", tool_name="fetch", tool_args={}, output="x" * 40_000
    )
    assert "omitted ...]" in envelope
    rows = [r for r in store.db.get_tool_results_for_session("S1") if r["tool_call_id"] == "huge-1"]
    assert "omitted ...]" in rows[0]["preview"]
