from unittest.mock import Mock

from agno.os.interfaces.slack.state import StreamState, TaskCard


class TestTrackTask:
    def test_creates_card(self):
        state = StreamState()
        state.track_task("tool_1", "Running search")
        assert "tool_1" in state.task_cards
        assert state.task_cards["tool_1"].title == "Running search"
        assert state.task_cards["tool_1"].status == "in_progress"

    def test_sets_progress_started(self):
        state = StreamState()
        assert state.progress_started is False
        state.track_task("t1", "Task")
        assert state.progress_started is True


class TestCompleteTask:
    def test_sets_status_complete(self):
        state = StreamState()
        state.track_task("t1", "Task")
        state.complete_task("t1")
        assert state.task_cards["t1"].status == "complete"

    def test_missing_key_noop(self):
        state = StreamState()
        state.complete_task("nonexistent")
        assert len(state.task_cards) == 0


class TestErrorTask:
    def test_sets_status_error(self):
        state = StreamState()
        state.track_task("t1", "Task")
        state.error_task("t1")
        assert state.task_cards["t1"].status == "error"

    def test_missing_key_noop(self):
        state = StreamState()
        state.error_task("nonexistent")
        assert len(state.task_cards) == 0


class TestResolveAllPending:
    def test_closes_in_progress_cards(self):
        state = StreamState()
        state.track_task("t1", "Task 1")
        state.track_task("t2", "Task 2")
        chunks = state.resolve_all_pending()
        assert len(chunks) == 2
        assert state.task_cards["t1"].status == "complete"
        assert state.task_cards["t2"].status == "complete"

    def test_skips_completed_cards(self):
        state = StreamState()
        state.track_task("t1", "Task 1")
        state.complete_task("t1")
        state.track_task("t2", "Task 2")
        chunks = state.resolve_all_pending()
        assert len(chunks) == 1
        assert chunks[0]["id"] == "t2"

    def test_skips_errored_cards(self):
        state = StreamState()
        state.track_task("t1", "Task 1")
        state.error_task("t1")
        chunks = state.resolve_all_pending()
        assert len(chunks) == 0

    def test_custom_status(self):
        state = StreamState()
        state.track_task("t1", "Task 1")
        chunks = state.resolve_all_pending(status="error")
        assert chunks[0]["status"] == "error"
        assert state.task_cards["t1"].status == "error"

    def test_empty_no_pending(self):
        state = StreamState()
        chunks = state.resolve_all_pending()
        assert chunks == []


class TestCollectMedia:
    def test_collects_all_types(self):
        state = StreamState()
        chunk = Mock(images=["img1"], videos=["vid1"], audio=["aud1"], files=["file1"])
        state.collect_media(chunk)
        assert state.images == ["img1"]
        assert state.videos == ["vid1"]
        assert state.audio == ["aud1"]
        assert state.files == ["file1"]

    def test_deduplicates(self):
        state = StreamState()
        chunk = Mock(images=["img1", "img1"], videos=[], audio=[], files=[])
        state.collect_media(chunk)
        state.collect_media(chunk)
        assert state.images == ["img1"]

    def test_none_attrs_tolerated(self):
        state = StreamState()
        chunk = Mock(spec=[])
        state.collect_media(chunk)
        assert state.images == []
        assert state.videos == []

    def test_none_lists_tolerated(self):
        state = StreamState()
        chunk = Mock(images=None, videos=None, audio=None, files=None)
        state.collect_media(chunk)
        assert state.images == []
