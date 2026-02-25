from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.os.interfaces.slack.helpers import (
    download_event_files_async,
    extract_event_context,
    member_name,
    send_slack_message_async,
    should_respond,
    task_id,
    upload_response_media_async,
)
from agno.os.interfaces.slack.state import StreamState


class TestTaskId:
    def test_truncates_long_name(self):
        result = task_id("A Very Long Agent Name Here", "id1")
        assert result == "a_very_long_agent_na_id1"
        assert len("a_very_long_agent_na") == 20

    def test_none_returns_base(self):
        assert task_id(None, "base_id") == "base_id"


class TestMemberName:
    def test_different_name_returned(self):
        chunk = Mock(agent_name="Research Agent")
        assert member_name(chunk, "Main Agent") == "Research Agent"

    def test_missing_attr_returns_none(self):
        chunk = Mock(spec=[])
        assert member_name(chunk, "Main Agent") is None


class TestShouldRespond:
    def test_app_mention_always_responds(self):
        assert should_respond({"type": "app_mention", "text": "hello"}, reply_to_mentions_only=True) is True

    def test_dm_always_responds(self):
        assert should_respond({"type": "message", "channel_type": "im"}, reply_to_mentions_only=True) is True

    def test_channel_blocked_with_mentions_only(self):
        assert should_respond({"type": "message", "channel_type": "channel"}, reply_to_mentions_only=True) is False

    def test_channel_allowed_without_mentions_only(self):
        assert should_respond({"type": "message", "channel_type": "channel"}, reply_to_mentions_only=False) is True

    def test_unknown_event_type(self):
        assert should_respond({"type": "reaction_added"}, reply_to_mentions_only=False) is False

    def test_app_mention_skipped_when_not_mentions_only(self):
        assert should_respond({"type": "app_mention", "channel_type": "channel"}, reply_to_mentions_only=False) is False

    def test_app_mention_dm_still_works(self):
        assert should_respond({"type": "app_mention", "channel_type": "im"}, reply_to_mentions_only=False) is True


class TestExtractEventContext:
    def test_prefers_thread_ts(self):
        ctx = extract_event_context({"text": "hi", "channel": "C1", "user": "U1", "ts": "111", "thread_ts": "222"})
        assert ctx["thread_id"] == "222"

    def test_falls_back_to_ts(self):
        ctx = extract_event_context({"text": "hi", "channel": "C1", "user": "U1", "ts": "111"})
        assert ctx["thread_id"] == "111"


class TestDownloadEventFilesAsync:
    @pytest.mark.asyncio
    async def test_video_routing(self):
        mock_response = Mock(content=b"video-data", status_code=200)
        mock_response.raise_for_status = Mock()
        event = {
            "files": [
                {"id": "F1", "name": "clip.mp4", "mimetype": "video/mp4", "url_private": "https://files.slack.com/F1"}
            ]
        }
        with patch("agno.os.interfaces.slack.helpers.httpx.AsyncClient") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            files, images, videos, audio, skipped = await download_event_files_async("xoxb-token", event, 1_073_741_824)
        assert len(videos) == 1
        assert len(files) == 0 and len(images) == 0
        assert len(skipped) == 0

    @pytest.mark.asyncio
    async def test_file_over_max_size_skipped(self):
        event = {
            "files": [
                {
                    "id": "F1",
                    "name": "huge.zip",
                    "mimetype": "application/zip",
                    "size": 50_000_000,
                    "url_private": "https://files.slack.com/F1",
                },
            ]
        }
        files, images, videos, audio, skipped = await download_event_files_async("xoxb-token", event, 25 * 1024 * 1024)
        assert len(skipped) == 1
        assert "huge.zip" in skipped[0]


class TestSendSlackMessageAsync:
    @pytest.mark.asyncio
    async def test_empty_skipped(self):
        client = AsyncMock()
        await send_slack_message_async(client, "C1", "ts1", "")
        client.chat_postMessage.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_send(self):
        client = AsyncMock()
        await send_slack_message_async(client, "C1", "ts1", "hello world")
        client.chat_postMessage.assert_called_once_with(channel="C1", text="hello world", thread_ts="ts1")

    @pytest.mark.asyncio
    async def test_long_message_batching(self):
        client = AsyncMock()
        await send_slack_message_async(client, "C1", "ts1", "x" * 50000)
        assert client.chat_postMessage.call_count == 2


class TestUploadResponseMediaAsync:
    @pytest.mark.asyncio
    async def test_all_types_uploaded(self):
        client = AsyncMock()
        response = Mock(
            images=[Mock(get_content_bytes=Mock(return_value=b"img"), filename="photo.png")],
            files=[Mock(get_content_bytes=Mock(return_value=b"file"), filename="doc.pdf")],
            videos=[Mock(get_content_bytes=Mock(return_value=b"vid"), filename=None)],
            audio=[Mock(get_content_bytes=Mock(return_value=b"aud"), filename=None)],
        )
        await upload_response_media_async(client, response, "C1", "ts1")
        assert client.files_upload_v2.call_count == 4

    @pytest.mark.asyncio
    async def test_exception_continues(self):
        client = AsyncMock()
        client.files_upload_v2 = AsyncMock(side_effect=RuntimeError("upload failed"))
        response = Mock(
            images=[Mock(get_content_bytes=Mock(return_value=b"img"), filename="photo.png")],
            files=[Mock(get_content_bytes=Mock(return_value=b"file"), filename="doc.pdf")],
            videos=None,
            audio=None,
        )
        with patch("agno.os.interfaces.slack.helpers.log_error"):
            await upload_response_media_async(client, response, "C1", "ts1")


# -- StreamState --


class TestStreamState:
    def test_track_complete_lifecycle(self):
        state = StreamState()
        state.track_task("tool_1", "Running search")
        assert state.task_cards["tool_1"].status == "in_progress"

        state.complete_task("tool_1")
        assert state.task_cards["tool_1"].status == "complete"

        state.complete_task("nonexistent")
        assert len(state.task_cards) == 1

    def test_resolve_all_pending_skips_finished(self):
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

    def test_collect_media_deduplicates(self):
        state = StreamState()
        chunk = Mock(images=["img1", "img1"], videos=["vid1"], audio=[], files=[])
        state.collect_media(chunk)
        state.collect_media(chunk)
        assert state.images == ["img1"]
        assert state.videos == ["vid1"]

    def test_collect_media_tolerates_none(self):
        state = StreamState()
        chunk = Mock(images=None, videos=None, audio=None, files=None)
        state.collect_media(chunk)
        assert state.images == []
