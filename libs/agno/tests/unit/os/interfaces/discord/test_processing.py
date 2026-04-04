from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.os.interfaces.discord.processing import run_entity, split_message, strip_mention


# split_message: Discord's 2000-char limit → [1/N] prefixed batches
class TestSplitMessage:
    def test_short_message_no_split(self):
        assert split_message("Hello world") == ["Hello world"]

    def test_exact_limit_no_split(self):
        msg = "x" * 1900
        assert split_message(msg) == [msg]

    def test_long_message_splits(self):
        msg = "x" * 4000
        batches = split_message(msg, max_chars=1900)
        assert len(batches) == 3
        assert batches[0].startswith("[1/3]")
        assert batches[1].startswith("[2/3]")
        assert batches[2].startswith("[3/3]")

    def test_custom_max_chars(self):
        msg = "abcdef"
        batches = split_message(msg, max_chars=3)
        assert len(batches) == 2
        assert batches[0].startswith("[1/2]")
        assert batches[1].startswith("[2/2]")

    def test_empty_message(self):
        assert split_message("") == [""]

    def test_single_char_over_limit(self):
        msg = "ab"
        batches = split_message(msg, max_chars=1)
        assert len(batches) == 2


# strip_mention: remove <@id> and <@!id> patterns from gateway messages
class TestStripMention:
    def test_standard_mention(self):
        assert strip_mention("<@123456> hello") == "hello"

    def test_nickname_mention(self):
        assert strip_mention("<@!123456> hello") == "hello"

    def test_multiple_mentions(self):
        assert strip_mention("<@111> <@!222> hello") == "hello"

    def test_no_mention(self):
        assert strip_mention("hello world") == "hello world"

    def test_mention_only(self):
        assert strip_mention("<@123>") == ""

    def test_mention_with_surrounding_text(self):
        assert strip_mention("hey <@123> how are you") == "hey  how are you"


# Build a mock RunResponse with sensible defaults; override any field via kwargs
def _make_response(**overrides):
    defaults = dict(
        status="OK",
        content="Hello from agent",
        reasoning_content=None,
        images=None,
        files=None,
        videos=None,
        audio=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


# Build a mock Replier with AsyncMock send methods matching the Replier protocol
def _make_replier():
    replier = MagicMock()
    replier.send_initial_response = AsyncMock()
    replier.send_followup = AsyncMock()
    replier.send_media = AsyncMock()
    return replier


# run_entity: the shared core — entity.arun() → format → replier.send_*()
class TestRunEntity:
    @pytest.fixture
    def mock_entity(self):
        entity = MagicMock()
        entity.arun = AsyncMock()
        return entity

    @pytest.fixture
    def replier(self):
        return _make_replier()

    async def test_normal_response(self, mock_entity, replier):
        mock_entity.arun = AsyncMock(return_value=_make_response())

        await run_entity(
            entity=mock_entity,
            message_text="Hello",
            user_id="user1",
            session_id="session1",
            replier=replier,
        )

        replier.send_initial_response.assert_called_once_with("Hello from agent")
        replier.send_followup.assert_not_called()

    async def test_none_response(self, mock_entity, replier):
        mock_entity.arun = AsyncMock(return_value=None)

        await run_entity(
            entity=mock_entity,
            message_text="Hello",
            user_id="user1",
            session_id="session1",
            replier=replier,
        )

        replier.send_initial_response.assert_called_once_with("No response generated.")

    async def test_error_response(self, mock_entity, replier):
        mock_entity.arun = AsyncMock(return_value=_make_response(status="ERROR", content="Something broke"))

        await run_entity(
            entity=mock_entity,
            message_text="Hello",
            user_id="user1",
            session_id="session1",
            replier=replier,
        )

        replier.send_initial_response.assert_called_once_with("Sorry, there was an error processing your message.")

    async def test_reasoning_content(self, mock_entity, replier):
        response = _make_response(
            content="Final answer",
            reasoning_content="Let me think...",
        )
        mock_entity.arun = AsyncMock(return_value=response)

        await run_entity(
            entity=mock_entity,
            message_text="Hello",
            user_id="user1",
            session_id="session1",
            replier=replier,
        )

        replier.send_initial_response.assert_called_once_with("*Let me think...*")
        assert replier.send_followup.call_count >= 1
        followup_texts = [call[0][0] for call in replier.send_followup.call_args_list]
        assert any("Final answer" in t for t in followup_texts)

    async def test_reasoning_disabled(self, mock_entity, replier):
        response = _make_response(
            content="Final answer",
            reasoning_content="Let me think...",
        )
        mock_entity.arun = AsyncMock(return_value=response)

        await run_entity(
            entity=mock_entity,
            message_text="Hello",
            user_id="user1",
            session_id="session1",
            replier=replier,
            show_reasoning=False,
        )

        replier.send_initial_response.assert_called_once_with("Final answer")
        replier.send_followup.assert_not_called()

    async def test_media_upload(self, mock_entity, replier):
        mock_image = MagicMock()
        mock_image.get_content_bytes.return_value = b"png-bytes"
        mock_image.filename = None

        response = _make_response(images=[mock_image])
        mock_entity.arun = AsyncMock(return_value=response)

        await run_entity(
            entity=mock_entity,
            message_text="Hello",
            user_id="user1",
            session_id="session1",
            replier=replier,
        )

        replier.send_media.assert_called_once_with(b"png-bytes", "image.png")

    async def test_empty_content_shows_placeholder(self, mock_entity, replier):
        response = _make_response(content=None)
        mock_entity.arun = AsyncMock(return_value=response)

        await run_entity(
            entity=mock_entity,
            message_text="Hello",
            user_id="user1",
            session_id="session1",
            replier=replier,
        )

        replier.send_initial_response.assert_called_once_with("(empty response)")

    async def test_long_response_splits(self, mock_entity, replier):
        long_text = "x" * 4000
        response = _make_response(content=long_text)
        mock_entity.arun = AsyncMock(return_value=response)

        await run_entity(
            entity=mock_entity,
            message_text="Hello",
            user_id="user1",
            session_id="session1",
            replier=replier,
        )

        replier.send_initial_response.assert_called_once()
        assert replier.send_followup.call_count >= 1

    async def test_exception_propagates(self, mock_entity, replier):
        mock_entity.arun = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await run_entity(
                entity=mock_entity,
                message_text="Hello",
                user_id="user1",
                session_id="session1",
                replier=replier,
            )
