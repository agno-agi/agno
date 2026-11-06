from agno.media import Audio, File, Image, Video
from agno.models.message import Message


class TestMessageMediaMetadata:
    def test_byte_backed_media_metadata_survives_round_trip(self):
        message = Message(
            role="user",
            content="media",
            images=[
                Image(
                    content=b"image-bytes",
                    id="image-1",
                    mime_type="image/png",
                    format="png",
                    detail="high",
                    original_prompt="original image prompt",
                    revised_prompt="revised image prompt",
                    alt_text="an image",
                    metadata={"source": "test"},
                )
            ],
            audio=[
                Audio(
                    content=b"audio-bytes",
                    id="audio-1",
                    mime_type="audio/wav",
                    format="wav",
                    duration=1.5,
                    sample_rate=16000,
                    channels=2,
                    transcript="hello",
                    expires_at=123,
                    metadata={"source": "test"},
                )
            ],
            videos=[
                Video(
                    content=b"video-bytes",
                    id="video-1",
                    mime_type="video/mp4",
                    format="mp4",
                    duration=12.5,
                    width=1920,
                    height=1080,
                    fps=24.0,
                    eta="10s",
                    original_prompt="original video prompt",
                    revised_prompt="revised video prompt",
                    metadata={"source": "test"},
                )
            ],
            files=[
                File(
                    content=b"file-bytes",
                    id="file-1",
                    mime_type="application/pdf",
                    file_type="pdf",
                    filename="test.pdf",
                    size=10,
                    format="pdf",
                    name="test-document",
                    external={"provider_id": "external-1"},
                    metadata={"source": "test"},
                )
            ],
            audio_output=Audio(
                content=b"output-audio",
                id="audio-output-1",
                mime_type="audio/wav",
                format="wav",
                duration=3.5,
                transcript="generated audio",
                metadata={"source": "test"},
            ),
        )

        restored = Message.from_dict(message.to_dict())

        image = restored.images[0]
        assert image.content == b"image-bytes"
        assert image.detail == "high"
        assert image.original_prompt == "original image prompt"
        assert image.revised_prompt == "revised image prompt"
        assert image.alt_text == "an image"
        assert image.metadata == {"source": "test"}

        audio = restored.audio[0]
        assert audio.content == b"audio-bytes"
        assert audio.format == "wav"
        assert audio.duration == 1.5
        assert audio.sample_rate == 16000
        assert audio.channels == 2
        assert audio.transcript == "hello"
        assert audio.expires_at == 123
        assert audio.metadata == {"source": "test"}

        video = restored.videos[0]
        assert video.content == b"video-bytes"
        assert video.duration == 12.5
        assert video.width == 1920
        assert video.height == 1080
        assert video.fps == 24.0
        assert video.eta == "10s"
        assert video.original_prompt == "original video prompt"
        assert video.revised_prompt == "revised video prompt"
        assert video.metadata == {"source": "test"}

        file = restored.files[0]
        assert file.content == b"file-bytes"
        assert file.file_type == "pdf"
        assert file.size == 10
        assert file.filename == "test.pdf"
        assert file.format == "pdf"
        assert file.name == "test-document"
        assert file.external == {"provider_id": "external-1"}
        assert file.metadata == {"source": "test"}

        audio_output = restored.audio_output
        assert audio_output is not None
        assert audio_output.content == b"output-audio"
        assert audio_output.format == "wav"
        assert audio_output.duration == 3.5
        assert audio_output.transcript == "generated audio"
        assert audio_output.metadata == {"source": "test"}
