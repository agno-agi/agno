"""Tests for media classes with media_reference and metadata fields."""

from agno.media import Audio, File, Image, Video
from agno.media_storage.reference import MediaReference


def _make_ref(media_type: str = "image") -> MediaReference:
    return MediaReference(
        media_id="test-id",
        storage_key="agno/media/test-id.png",
        storage_backend="s3",
        url="https://example.com/test-id.png",
        mime_type="image/png",
        media_type=media_type,
    )


class TestImageMediaReference:
    def test_image_with_media_reference(self):
        ref = _make_ref("image")
        img = Image(url=ref.url, media_reference=ref, id="test-id")
        assert img.media_reference is not None
        assert img.media_reference.storage_key == "agno/media/test-id.png"

    def test_image_to_dict_with_reference(self):
        ref = _make_ref("image")
        img = Image(url=ref.url, media_reference=ref, id="test-id", detail="high")
        d = img.to_dict()
        assert "media_reference" in d
        assert d["media_reference"]["storage_key"] == "agno/media/test-id.png"
        assert "content" not in d
        assert d.get("detail") == "high"  # Class-specific field preserved

    def test_image_to_dict_with_metadata(self):
        img = Image(url="https://example.com/img.png", metadata={"source": "camera"})
        d = img.to_dict()
        assert d["metadata"] == {"source": "camera"}

    def test_image_to_dict_without_reference(self):
        img = Image(url="https://example.com/img.png")
        d = img.to_dict()
        assert "media_reference" not in d
        assert "metadata" not in d

    def test_image_media_reference_only(self):
        ref = _make_ref("image")
        img = Image(media_reference=ref)
        assert img.id is not None  # Auto-generated
        assert img.media_reference.storage_key == "agno/media/test-id.png"


class TestAudioMediaReference:
    def test_audio_with_media_reference(self):
        ref = MediaReference(
            media_id="aud-1",
            storage_key="agno/media/aud-1.mp3",
            storage_backend="s3",
            url="https://example.com/aud-1.mp3",
        )
        audio = Audio(url=ref.url, media_reference=ref, id="aud-1", transcript="hello")
        d = audio.to_dict()
        assert "media_reference" in d
        assert "content" not in d
        assert d.get("transcript") == "hello"


class TestVideoMediaReference:
    def test_video_with_media_reference(self):
        ref = MediaReference(
            media_id="vid-1",
            storage_key="agno/media/vid-1.mp4",
            storage_backend="s3",
            url="https://example.com/vid-1.mp4",
        )
        video = Video(url=ref.url, media_reference=ref, id="vid-1", width=1920, height=1080)
        d = video.to_dict()
        assert "media_reference" in d
        assert "content" not in d
        assert d.get("width") == 1920
        assert d.get("height") == 1080


class TestFileMediaReference:
    def test_file_with_media_reference(self):
        ref = MediaReference(
            media_id="file-1",
            storage_key="agno/media/file-1.pdf",
            storage_backend="s3",
            url="https://example.com/file-1.pdf",
        )
        f = File(url=ref.url, media_reference=ref, id="file-1", filename="report.pdf")
        d = f.to_dict()
        assert "media_reference" in d
        assert "content" not in d
        assert d.get("filename") == "report.pdf"

    def test_file_media_reference_only(self):
        ref = MediaReference(
            media_id="file-2",
            storage_key="key",
            storage_backend="local",
            url="file:///tmp/file-2.txt",
        )
        f = File(media_reference=ref)
        assert f.media_reference is not None

    def test_file_to_dict_include_base64(self):
        f = File(content=b"hello", mime_type="text/plain")
        d = f.to_dict(include_base64_content=True)
        assert "content" in d
        assert "media_reference" not in d

    def test_file_to_dict_exclude_base64(self):
        f = File(content=b"hello", mime_type="text/plain")
        d = f.to_dict(include_base64_content=False)
        assert "content" not in d
