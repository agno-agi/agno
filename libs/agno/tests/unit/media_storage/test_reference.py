"""Tests for MediaReference serialization round-trip."""

from agno.media_storage.reference import MediaReference


def test_media_reference_to_dict():
    ref = MediaReference(
        media_id="img-123",
        storage_key="agno/media/img-123.png",
        storage_backend="s3",
        bucket="my-bucket",
        region="us-east-1",
        url="https://my-bucket.s3.amazonaws.com/agno/media/img-123.png",
        mime_type="image/png",
        filename="photo.png",
        size=1024,
        content_hash="abc123",
        media_type="image",
    )
    d = ref.to_dict()
    assert d["media_id"] == "img-123"
    assert d["storage_key"] == "agno/media/img-123.png"
    assert d["storage_backend"] == "s3"
    assert d["bucket"] == "my-bucket"
    assert d["url"] == "https://my-bucket.s3.amazonaws.com/agno/media/img-123.png"
    assert "metadata" not in d  # None fields excluded


def test_media_reference_from_dict():
    data = {
        "media_id": "aud-456",
        "storage_key": "agno/media/aud-456.mp3",
        "storage_backend": "s3",
        "url": "https://example.com/aud-456.mp3",
        "mime_type": "audio/mpeg",
    }
    ref = MediaReference.from_dict(data)
    assert ref.media_id == "aud-456"
    assert ref.storage_key == "agno/media/aud-456.mp3"
    assert ref.storage_backend == "s3"
    assert ref.bucket is None
    assert ref.url == "https://example.com/aud-456.mp3"


def test_media_reference_round_trip():
    ref = MediaReference(
        media_id="vid-789",
        storage_key="agno/media/vid-789.mp4",
        storage_backend="local",
        url="file:///tmp/media/vid-789.mp4",
        metadata={"department": "marketing"},
    )
    d = ref.to_dict()
    reconstructed = MediaReference.from_dict(d)
    assert reconstructed.media_id == ref.media_id
    assert reconstructed.storage_key == ref.storage_key
    assert reconstructed.storage_backend == ref.storage_backend
    assert reconstructed.url == ref.url
    assert reconstructed.metadata == {"department": "marketing"}


def test_media_reference_exclude_none():
    ref = MediaReference(
        media_id="test",
        storage_key="key",
        storage_backend="s3",
    )
    d = ref.to_dict()
    assert "bucket" not in d
    assert "region" not in d
    assert "url" not in d
    assert "mime_type" not in d
    assert "filename" not in d
    assert "size" not in d
    assert "content_hash" not in d
    assert "media_type" not in d
    assert "metadata" not in d
