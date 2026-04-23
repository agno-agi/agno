"""Tests for EventsBuffer — monotonic indexing and trim correctness."""

from agno.os.managers import EventsBuffer
from agno.run.agent import RunContentEvent


def _make_event(content: str) -> RunContentEvent:
    return RunContentEvent(content=content)


class TestMonotonicIndex:
    """event_index must increase monotonically even after buffer trims."""

    def test_indices_monotonic_no_trim(self):
        buf = EventsBuffer(max_events_per_run=100)
        indices = [buf.add_event("r1", _make_event(f"e{i}")) for i in range(10)]
        assert indices == list(range(10))

    def test_indices_monotonic_after_trim(self):
        buf = EventsBuffer(max_events_per_run=3)
        indices = [buf.add_event("r1", _make_event(f"e{i}")) for i in range(7)]
        # Must be 0,1,2,3,4,5,6 — NOT 0,1,2,3,3,3,3
        assert indices == [0, 1, 2, 3, 4, 5, 6]

    def test_buffer_size_capped(self):
        buf = EventsBuffer(max_events_per_run=3)
        for i in range(7):
            buf.add_event("r1", _make_event(f"e{i}"))
        # Only last 3 events kept in memory
        assert len(buf.events["r1"]) == 3
        assert buf.events["r1"][0].content == "e4"
        assert buf.events["r1"][2].content == "e6"


class TestGetEventsAfterTrim:
    """get_events must return correct (index, event) tuples using monotonic indices after trims."""

    def test_get_all_events_no_trim(self):
        buf = EventsBuffer(max_events_per_run=100)
        for i in range(5):
            buf.add_event("r1", _make_event(f"e{i}"))
        events = buf.get_events("r1")
        assert len(events) == 5
        # Should return tuples with correct monotonic indices
        assert events[0] == (0, events[0][1])
        assert events[4] == (4, events[4][1])

    def test_get_events_since_index_no_trim(self):
        buf = EventsBuffer(max_events_per_run=100)
        for i in range(5):
            buf.add_event("r1", _make_event(f"e{i}"))
        # Client has 0,1,2 — wants 3,4
        events = buf.get_events("r1", last_event_index=2)
        assert len(events) == 2
        assert events[0][0] == 3
        assert events[0][1].content == "e3"
        assert events[1][0] == 4
        assert events[1][1].content == "e4"

    def test_get_events_since_index_after_trim(self):
        buf = EventsBuffer(max_events_per_run=5)
        for i in range(10):
            buf.add_event("r1", _make_event(f"e{i}"))
        # Buffer holds e5..e9 (indices 5-9). Client has up to index 7.
        events = buf.get_events("r1", last_event_index=7)
        assert len(events) == 2
        assert events[0][0] == 8
        assert events[0][1].content == "e8"
        assert events[1][0] == 9
        assert events[1][1].content == "e9"

    def test_get_events_client_behind_buffer(self):
        """Client's last index is older than what the buffer still holds."""
        buf = EventsBuffer(max_events_per_run=3)
        for i in range(10):
            buf.add_event("r1", _make_event(f"e{i}"))
        # Buffer holds e7,e8,e9. Client has index 2 — way behind.
        # Should return everything in the buffer with correct indices.
        events = buf.get_events("r1", last_event_index=2)
        assert len(events) == 3
        assert events[0][0] == 7
        assert events[0][1].content == "e7"
        assert events[2][0] == 9
        assert events[2][1].content == "e9"

    def test_get_events_client_caught_up(self):
        buf = EventsBuffer(max_events_per_run=5)
        for i in range(10):
            buf.add_event("r1", _make_event(f"e{i}"))
        # Client has index 9 (the latest)
        events = buf.get_events("r1", last_event_index=9)
        assert events == []

    def test_get_events_none_index_returns_all(self):
        buf = EventsBuffer(max_events_per_run=3)
        for i in range(7):
            buf.add_event("r1", _make_event(f"e{i}"))
        events = buf.get_events("r1", last_event_index=None)
        assert len(events) == 3
        # After trim, buffer holds e4,e5,e6 with indices 4,5,6
        assert events[0][0] == 4
        assert events[0][1].content == "e4"

    def test_get_events_unknown_run(self):
        buf = EventsBuffer(max_events_per_run=10)
        assert buf.get_events("nonexistent") == []
        assert buf.get_events("nonexistent", last_event_index=5) == []


class TestCleanup:
    """Cleanup should remove index counters alongside event data."""

    def test_cleanup_removes_index_counter(self):
        buf = EventsBuffer(max_events_per_run=10)
        buf.add_event("r1", _make_event("e0"))
        assert "r1" in buf._next_index
        buf.cleanup_run("r1")
        assert "r1" not in buf._next_index
        assert "r1" not in buf.events

    def test_new_run_after_cleanup_starts_at_zero(self):
        buf = EventsBuffer(max_events_per_run=10)
        for i in range(5):
            buf.add_event("r1", _make_event(f"e{i}"))
        buf.cleanup_run("r1")
        # New run with same ID starts fresh
        idx = buf.add_event("r1", _make_event("fresh"))
        assert idx == 0


class TestMultipleRuns:
    """Indices are independent per run_id."""

    def test_independent_counters(self):
        buf = EventsBuffer(max_events_per_run=3)
        for i in range(5):
            idx_a = buf.add_event("a", _make_event(f"a{i}"))
            idx_b = buf.add_event("b", _make_event(f"b{i}"))
            assert idx_a == i
            assert idx_b == i

    def test_get_events_isolated(self):
        buf = EventsBuffer(max_events_per_run=3)
        for i in range(5):
            buf.add_event("a", _make_event(f"a{i}"))
        for i in range(8):
            buf.add_event("b", _make_event(f"b{i}"))
        # Run "a": buffer has a2,a3,a4 (indices 2-4)
        events_a = buf.get_events("a", last_event_index=3)
        assert len(events_a) == 1
        assert events_a[0][0] == 4
        assert events_a[0][1].content == "a4"
        # Run "b": buffer has b5,b6,b7 (indices 5-7)
        events_b = buf.get_events("b", last_event_index=5)
        assert len(events_b) == 2
        assert events_b[0][0] == 6
        assert events_b[0][1].content == "b6"
