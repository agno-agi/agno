"""Tests for build_storage_key and the media-id sanitizing every backend shares."""

import tempfile
from unittest.mock import MagicMock

import pytest

from agno.media.storage.local import LocalMediaStorage
from agno.media.storage.utils import build_storage_key


def test_every_backend_builds_the_same_key():
    """The key builder is shared, so a media id maps to one key whatever the backend."""
    from agno.media.storage.gcs import GCSMediaStorage
    from agno.media.storage.s3 import AsyncS3MediaStorage, S3MediaStorage

    expected = build_storage_key("media-1", prefix="agno/media/", filename="photo.png")
    assert expected == "agno/media/media-1.png"

    mock_client = MagicMock()
    s3 = S3MediaStorage(bucket="b")
    s3._client = mock_client
    assert s3.upload("media-1", b"x", filename="photo.png") == expected

    async_s3 = AsyncS3MediaStorage(bucket="b")
    gcs = GCSMediaStorage(bucket="b")
    for storage in (async_s3, gcs):
        assert build_storage_key("media-1", prefix=storage.prefix, filename="photo.png") == expected

    with tempfile.TemporaryDirectory() as tmpdir:
        # Local nests under base_path instead of carrying a key prefix.
        assert LocalMediaStorage(base_path=tmpdir).upload("media-1", b"x", filename="photo.png") == "media-1.png"


def test_build_storage_key_prefers_the_filename_extension_over_the_mime_type():
    assert build_storage_key("m", filename="a.tar.gz", mime_type="image/png") == "m.gz"
    assert build_storage_key("m", mime_type="image/png") == "m.png"
    assert build_storage_key("m") == "m"


def test_build_storage_key_sanitizes_traversal():
    assert build_storage_key("../../etc/passwd", prefix="agno/media/") == "agno/media/etc_passwd"


def test_storage_key_extension_is_sanitized_like_the_media_id():
    """A caller-supplied filename must not put path components into the key.

    The id has always been sanitized; the extension was taken raw, so a filename could add a
    separator (splitting the key across a prefix) or a tail long enough for the filesystem to
    reject the write, which fell back to inline base64.
    """
    assert build_storage_key("mid", prefix="p/", filename="report.csv") == "p/mid.csv"
    assert build_storage_key("mid", prefix="p/", filename="report.v1/final") == "p/mid.v1final"
    assert build_storage_key("mid", prefix="p/", filename="a./../../../tmp/pwned") == "p/mid.tmppwned"
    assert build_storage_key("mid", prefix="p/", filename="x.<script>") == "p/mid.script"
    assert len(build_storage_key("mid", prefix="p/", filename="x." + "A" * 300)) < 40


def test_storage_key_falls_back_to_mime_type_when_the_extension_sanitizes_away():
    """An extension made entirely of stripped characters leaves the mime type to name the file."""
    assert build_storage_key("mid", prefix="p/", filename="report.///", mime_type="image/png") == "p/mid.png"


def test_the_same_media_bytes_always_map_to_the_same_key():
    """Keys are content-addressed and carry no session or run id.

    One media id and one payload always name this one object, so two sessions offloading the
    same bytes — ``fork_session`` deep-copies MediaReferences verbatim — end up sharing it
    rather than each holding a copy of their own.
    """
    first = build_storage_key("img-1-0123456789abcdef", prefix="agno/media/", mime_type="image/png")
    second = build_storage_key("img-1-0123456789abcdef", prefix="agno/media/", mime_type="image/png")

    assert first == second
    assert "session" not in first


@pytest.mark.parametrize(
    "mime_type, expected",
    [
        # mimetypes returns None for all of these, and agno mints them itself
        ("audio/wav", ".wav"),
        ("audio/mp3", ".mp3"),
        ("audio/flac", ".flac"),
        ("video/mov", ".mov"),
        ("video/avi", ".avi"),
        # get_mime_type synthesizes "{category}/{format}" for anything it has no entry for
        ("audio/m4a", ".m4a"),
        ("video/mkv", ".mkv"),
        # compound types must not be mangled into .svgxml / .octetstream — mimetypes owns these
        ("image/svg+xml", ".svg"),
        ("application/octet-stream", ".bin"),
    ],
)
def test_a_mime_type_python_cannot_map_still_gets_a_suffix(mime_type, expected):
    """Without the subtype fallback a TTS clip or a .mov is stored with no suffix at all."""
    assert build_storage_key("sid-mid-hash", mime_type=mime_type).endswith(expected)


@pytest.mark.parametrize("mime_type", ["application/vnd.custom-thing", "weird", "x/", ""])
def test_an_unmappable_mime_type_yields_no_suffix_rather_than_a_mangled_one(mime_type):
    """The fallback is deliberately narrow: a subtype that is not already a bare token is
    dropped rather than turned into a nonsense extension."""
    assert build_storage_key("sid-mid-hash", mime_type=mime_type) == "sid-mid-hash"
