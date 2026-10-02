"""Tests that Message round-trips generated media output.

Message declares audio_output, image_output and video_output, and from_dict
reconstructs all three. to_dict only wrote audio_output, so a generated image
or video was dropped whenever a message was persisted and read back. A
byte-backed image or video also came back stripped, because from_dict passed
only id, mime_type and format to from_base64.
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

    def test_byte_backed_media_output_keeps_its_fields(self):
        message = Message(
            role="assistant",
            content="Here is your media",
            image_output=Image(
                content=b"fake-png-bytes",
                id="img-1",
                format="png",
                mime_type="image/png",
                detail="high",
                original_prompt="a red bicycle",
                revised_prompt="a red bicycle on a wet street",
                alt_text="A red bicycle",
                metadata={"source": "unit-test"},
            ),
            video_output=Video(
                content=b"fake-mp4-bytes",
                id="vid-1",
                format="mp4",
                mime_type="video/mp4",
                duration=12.5,
                width=1920,
                height=1080,
                fps=24.0,
                eta="10s",
                original_prompt="a cat",
                revised_prompt="a cat on a sofa",
                metadata={"source": "unit-test"},
            ),
        )

        restored = Message.from_dict(message.to_dict())

        image = restored.image_output
        assert image is not None
        assert image.content == b"fake-png-bytes"
        assert image.detail == "high"
        assert image.original_prompt == "a red bicycle"
        assert image.revised_prompt == "a red bicycle on a wet street"
        assert image.alt_text == "A red bicycle"
        assert image.metadata == {"source": "unit-test"}

        video = restored.video_output
        assert video is not None
        assert video.content == b"fake-mp4-bytes"
        assert video.duration == 12.5
        assert video.width == 1920
        assert video.height == 1080
        assert video.fps == 24.0
        assert video.eta == "10s"
        assert video.original_prompt == "a cat"
        assert video.revised_prompt == "a cat on a sofa"
        assert video.metadata == {"source": "unit-test"}
