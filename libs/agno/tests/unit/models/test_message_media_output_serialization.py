"""Tests that Message.to_dict serializes generated media output.

Message declares audio_output, image_output and video_output, and from_dict
reconstructs all three. to_dict only wrote audio_output, so a generated image
or video was dropped whenever a message was persisted and read back.
"""

from agno.media import Audio, Image, Video
from agno.models.message import Message


class TestMessageMediaOutputSerialization:
    def test_to_dict_includes_image_and_video_output(self):
        message = Message(
            role="assistant",
            content="Here is your media",
            image_output=Image(url="https://example.com/generated.png", id="img-1"),
            video_output=Video(url="https://example.com/generated.mp4", id="vid-1"),
        )

        message_dict = message.to_dict()

        assert "image_output" in message_dict
        assert "video_output" in message_dict
        assert message_dict["image_output"]["id"] == "img-1"
        assert message_dict["video_output"]["id"] == "vid-1"

    def test_media_output_survives_a_round_trip(self):
        message = Message(
            role="assistant",
            content="Here is your media",
            audio_output=Audio(url="https://example.com/generated.wav", id="aud-1"),
            image_output=Image(url="https://example.com/generated.png", id="img-1"),
            video_output=Video(url="https://example.com/generated.mp4", id="vid-1"),
        )

        restored = Message.from_dict(message.to_dict())

        assert restored.audio_output is not None
        assert restored.image_output is not None
        assert restored.video_output is not None
        assert restored.image_output.id == "img-1"
        assert restored.video_output.id == "vid-1"
