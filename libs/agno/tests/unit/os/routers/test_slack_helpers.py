from unittest.mock import Mock, patch

import pytest

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
    def test_with_agent_name(self):
        result = task_id("My Agent", "call_123")
        assert result == "my_agent_call_123"

    def test_truncates_long_name(self):
        result = task_id("A Very Long Agent Name Here", "id1")
        assert result == "a_very_long_agent_na_id1"
        assert len("a_very_long_agent_na") == 20

    def test_none_returns_base(self):
        result = task_id(None, "base_id")
        assert result == "base_id"


class TestMemberName:
    def test_different_name_returned(self):
        chunk = Mock(agent_name="Research Agent")
        assert member_name(chunk, "Main Agent") == "Research Agent"

    def test_same_name_returns_none(self):
        chunk = Mock(agent_name="Main Agent")
        assert member_name(chunk, "Main Agent") is None

    def test_missing_attr_returns_none(self):
        chunk = Mock(spec=[])
        assert member_name(chunk, "Main Agent") is None

    def test_non_string_returns_none(self):
        chunk = Mock(agent_name=42)
        assert member_name(chunk, "Main Agent") is None


class TestShouldRespond:
    def test_app_mention_always_responds(self):
        event = {"type": "app_mention", "text": "hello"}
        assert should_respond(event, reply_to_mentions_only=True) is True

    def test_dm_always_responds(self):
        event = {"type": "message", "channel_type": "im"}
        assert should_respond(event, reply_to_mentions_only=True) is True

    def test_channel_blocked_with_mentions_only(self):
        event = {"type": "message", "channel_type": "channel"}
        assert should_respond(event, reply_to_mentions_only=True) is False

    def test_channel_allowed_without_mentions_only(self):
        event = {"type": "message", "channel_type": "channel"}
        assert should_respond(event, reply_to_mentions_only=False) is True

    def test_unknown_event_type(self):
        event = {"type": "reaction_added"}
        assert should_respond(event, reply_to_mentions_only=False) is False


class TestExtractEventContext:
    def test_prefers_thread_ts(self):
        event = {"text": "hello", "channel": "C1", "user": "U1", "ts": "111", "thread_ts": "222"}
        ctx = extract_event_context(event)
        assert ctx["thread_id"] == "222"
        assert ctx["message_text"] == "hello"
        assert ctx["channel_id"] == "C1"
        assert ctx["user"] == "U1"

    def test_falls_back_to_ts(self):
        event = {"text": "hello", "channel": "C1", "user": "U1", "ts": "111"}
        ctx = extract_event_context(event)
        assert ctx["thread_id"] == "111"


class TestDownloadEventFiles:
    def test_video_routing(self):
        slack = Mock()
        slack.download_file_bytes = Mock(return_value=b"video-data")
        event = {"files": [{"id": "F1", "name": "clip.mp4", "mimetype": "video/mp4"}]}
        files, images, videos, audio = download_event_files(slack, event)
        assert len(videos) == 1
        assert videos[0].content == b"video-data"
        assert len(files) == 0 and len(images) == 0 and len(audio) == 0

    def test_audio_routing(self):
        slack = Mock()
        slack.download_file_bytes = Mock(return_value=b"audio-data")
        event = {"files": [{"id": "F1", "name": "voice.mp3", "mimetype": "audio/mpeg"}]}
        files, images, videos, audio = download_event_files(slack, event)
        assert len(audio) == 1
        assert audio[0].content == b"audio-data"

    def test_download_failure_logged(self):
        slack = Mock()
        slack.download_file_bytes = Mock(side_effect=RuntimeError("network error"))
        event = {"files": [{"id": "F1", "name": "file.txt", "mimetype": "text/plain"}]}
        with patch("agno.os.interfaces.slack.helpers.log_error") as mock_log:
            files, images, videos, audio = download_event_files(slack, event)
            mock_log.assert_called_once()
        assert len(files) == 0

    def test_null_content_skipped(self):
        slack = Mock()
        slack.download_file_bytes = Mock(return_value=None)
        event = {"files": [{"id": "F1", "name": "gone.txt", "mimetype": "text/plain"}]}
        files, images, videos, audio = download_event_files(slack, event)
        assert len(files) == 0


class TestSendSlackMessage:
    def test_empty_skipped(self):
        slack = Mock()
        send_slack_message(slack, "C1", "ts1", "")
        slack.send_message_thread.assert_not_called()

    def test_whitespace_skipped(self):
        slack = Mock()
        send_slack_message(slack, "C1", "ts1", "   ")
        slack.send_message_thread.assert_not_called()

    def test_normal_send(self):
        slack = Mock()
        send_slack_message(slack, "C1", "ts1", "hello world")
        slack.send_message_thread.assert_called_once_with(channel="C1", text="hello world", thread_ts="ts1")

    def test_italics_formatting(self):
        slack = Mock()
        send_slack_message(slack, "C1", "ts1", "line1\nline2", italics=True)
        call_args = slack.send_message_thread.call_args
        assert call_args.kwargs["text"] == "_line1_\n_line2_"

    def test_long_message_batching(self):
        slack = Mock()
        long_msg = "x" * 50000
        send_slack_message(slack, "C1", "ts1", long_msg)
        assert slack.send_message_thread.call_count == 2
        first_call = slack.send_message_thread.call_args_list[0]
        assert first_call.kwargs["text"].startswith("[1/2]")


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

    def test_empty_bytes_skipped(self):
        slack = Mock()
        response = Mock(
            images=[Mock(get_content_bytes=Mock(return_value=b""))],
            files=None,
            videos=None,
            audio=None,
        )
        upload_response_media(slack, response, "C1", "ts1")
        slack.upload_file.assert_not_called()

    def test_exception_continues(self):
        slack = Mock()
        slack.upload_file = Mock(side_effect=RuntimeError("upload failed"))
        response = Mock(
            images=[Mock(get_content_bytes=Mock(return_value=b"img"), filename="photo.png")],
            files=[Mock(get_content_bytes=Mock(return_value=b"file"), filename="doc.pdf")],
            videos=None,
            audio=None,
        )
        with patch("agno.os.interfaces.slack.helpers.log_error") as mock_log:
            upload_response_media(slack, response, "C1", "ts1")
            assert mock_log.call_count == 2
