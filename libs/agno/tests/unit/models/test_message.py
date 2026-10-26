"""Tests for the Message class."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from agno.models.message import Message


class TestGetContentString:
    """Tests for Message.get_content_string() method."""

    def test_string_content(self):
        """Test that string content is returned as-is."""
        message = Message(role="assistant", content="Hello, world!")
        assert message.get_content_string() == "Hello, world!"

    def test_empty_list_content_returns_empty_string(self):
        """Test that empty list content returns empty string, not '[]'.

        This is a regression test for the bug where empty content lists
        (common after tool execution) would return '[]' string.
        """
        message = Message(role="assistant", content=[])
        result = message.get_content_string()
        assert result == ""
        assert result != "[]"

    def test_list_with_text_dict(self):
        """Test that list with text dict returns the text."""
        message = Message(role="assistant", content=[{"text": "Hello from list"}])
        assert message.get_content_string() == "Hello from list"

    def test_list_with_text_dict_empty_text(self):
        """Test that list with empty text returns empty string."""
        message = Message(role="assistant", content=[{"text": ""}])
        assert message.get_content_string() == ""

    def test_list_with_non_text_dict(self):
        """Test that list with non-text dict returns JSON."""
        content = [{"type": "image", "url": "http://example.com/image.png"}]
        message = Message(role="assistant", content=content)
        assert message.get_content_string() == json.dumps(content)

    def test_list_with_multiple_items(self):
        """Test that list with multiple items returns first text."""
        message = Message(
            role="assistant",
            content=[{"text": "First"}, {"text": "Second"}],
        )
        assert message.get_content_string() == "First"

    def test_none_content(self):
        """Test that None content returns empty string."""
        message = Message(role="assistant", content=None)
        assert message.get_content_string() == ""

    def test_list_with_strings(self):
        """Test that list of strings returns JSON dump."""
        content = ["item1", "item2"]
        message = Message(role="assistant", content=content)
        assert message.get_content_string() == json.dumps(content)


class TestFromDict:
    @pytest.mark.parametrize(
        "field", ["images", "audio", "videos", "files", "audio_output", "image_output", "video_output"]
    )
    def test_media_reconstruction_preserves_serialized_input(self, field):
        media = {"id": "media-1", "content": "bWVkaWE="}
        payload = {
            "id": "message-1",
            "created_at": 0,
            "role": "user",
            field: [media] if field in {"images", "audio", "videos", "files"} else media,
        }
        original = deepcopy(payload)

        first = Message.from_dict(payload)
        second = Message.from_dict(payload)

        reconstructed = getattr(first, field)
        if isinstance(reconstructed, list):
            reconstructed = reconstructed[0]
        assert reconstructed.content == b"media"
        assert reconstructed.id == "media-1"
        assert first.model_dump() == second.model_dump()
        assert payload == original
        assert json.loads(json.dumps(payload)) == original

    @pytest.mark.parametrize("metrics", [{"input_tokens": 2}, None, "invalid"])
    def test_metrics_reconstruction_preserves_serialized_input(self, metrics):
        payload = {"role": "assistant", "metrics": metrics}
        original = deepcopy(payload)

        message = Message.from_dict(payload)

        assert message.metrics.input_tokens == (2 if isinstance(metrics, dict) else 0)
        assert payload == original

    def test_failed_validation_preserves_serialized_input(self):
        payload = {"images": [{"id": "image-1", "content": "aW1hZ2U="}], "metrics": None}
        original = deepcopy(payload)

        with pytest.raises(ValidationError):
            Message.from_dict(payload)

        assert payload == original
