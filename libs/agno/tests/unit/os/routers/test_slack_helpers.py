from unittest.mock import Mock, patch

from agno.os.interfaces.slack.helpers import (
    download_event_files,
    extract_event_context,
    member_name,
    send_slack_message,
    should_respond,
    task_id,
    upload_response_media,
)


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


class TestExtractEventContext:
    def test_prefers_thread_ts(self):
        ctx = extract_event_context({"text": "hi", "channel": "C1", "user": "U1", "ts": "111", "thread_ts": "222"})
        assert ctx["thread_id"] == "222"

    def test_falls_back_to_ts(self):
        ctx = extract_event_context({"text": "hi", "channel": "C1", "user": "U1", "ts": "111"})
        assert ctx["thread_id"] == "111"


class TestDownloadEventFiles:
    def test_video_routing(self):
        slack = Mock()
        slack.download_file_bytes = Mock(return_value=b"video-data")
        event = {"files": [{"id": "F1", "name": "clip.mp4", "mimetype": "video/mp4"}]}
        files, images, videos, audio = download_event_files(slack, event)
        assert len(videos) == 1
        assert len(files) == 0 and len(images) == 0

    def test_download_failure_logged(self):
        slack = Mock()
        slack.download_file_bytes = Mock(side_effect=RuntimeError("network error"))
        event = {"files": [{"id": "F1", "name": "file.txt", "mimetype": "text/plain"}]}
        with patch("agno.os.interfaces.slack.helpers.log_error") as mock_log:
            files, images, videos, audio = download_event_files(slack, event)
            mock_log.assert_called_once()
        assert len(files) == 0


class TestSendSlackMessage:
    def test_empty_skipped(self):
        slack = Mock()
        send_slack_message(slack, "C1", "ts1", "")
        slack.send_message_thread.assert_not_called()

    def test_normal_send(self):
        slack = Mock()
        send_slack_message(slack, "C1", "ts1", "hello world")
        slack.send_message_thread.assert_called_once_with(channel="C1", text="hello world", thread_ts="ts1")

    def test_long_message_batching(self):
        slack = Mock()
        send_slack_message(slack, "C1", "ts1", "x" * 50000)
        assert slack.send_message_thread.call_count == 2


class TestUploadResponseMedia:
    def test_all_types_uploaded(self):
        slack = Mock()
        response = Mock(
            images=[Mock(get_content_bytes=Mock(return_value=b"img"), filename="photo.png")],
            files=[Mock(get_content_bytes=Mock(return_value=b"file"), filename="doc.pdf")],
            videos=[Mock(get_content_bytes=Mock(return_value=b"vid"), filename=None)],
            audio=[Mock(get_content_bytes=Mock(return_value=b"aud"), filename=None)],
        )
        upload_response_media(slack, response, "C1", "ts1")
        assert slack.upload_file.call_count == 4

    def test_exception_continues(self):
        slack = Mock()
        slack.upload_file = Mock(side_effect=RuntimeError("upload failed"))
        response = Mock(
            images=[Mock(get_content_bytes=Mock(return_value=b"img"), filename="photo.png")],
            files=[Mock(get_content_bytes=Mock(return_value=b"file"), filename="doc.pdf")],
            videos=None,
            audio=None,
        )
        with patch("agno.os.interfaces.slack.helpers.log_error"):
            upload_response_media(slack, response, "C1", "ts1")
