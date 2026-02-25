from unittest.mock import Mock

from agno.os.interfaces.slack.state import StreamState


def test_track_complete_lifecycle():
    state = StreamState()
    state.track_task("tool_1", "Running search")
    assert state.task_cards["tool_1"].status == "in_progress"

    state.complete_task("tool_1")
    assert state.task_cards["tool_1"].status == "complete"

    state.complete_task("nonexistent")
    assert len(state.task_cards) == 1


def test_resolve_all_pending_skips_finished():
    state = StreamState()
    state.track_task("t1", "Task 1")
    state.complete_task("t1")
    state.track_task("t2", "Task 2")
    state.track_task("t3", "Task 3")
    state.error_task("t3")

    chunks = state.resolve_all_pending()
    assert len(chunks) == 1
    assert chunks[0]["id"] == "t2"
    assert state.task_cards["t1"].status == "complete"
    assert state.task_cards["t2"].status == "complete"
    assert state.task_cards["t3"].status == "error"


def test_collect_media_deduplicates():
    state = StreamState()
    chunk = Mock(images=["img1", "img1"], videos=["vid1"], audio=[], files=[])
    state.collect_media(chunk)
    state.collect_media(chunk)
    assert state.images == ["img1"]
    assert state.videos == ["vid1"]


def test_collect_media_tolerates_none():
    state = StreamState()
    chunk = Mock(images=None, videos=None, audio=None, files=None)
    state.collect_media(chunk)
    assert state.images == []
