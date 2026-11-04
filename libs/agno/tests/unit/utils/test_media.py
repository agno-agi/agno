from agno.utils.media import get_image_type, resolve_image_mime_type

PNG_SIGNATURE = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"
GIF_HEADER = b"GIF89a"
JPEG_SOI = b"\xff\xd8\xff\xe0\x00\x10"
WEBP_RIFF = b"RIFF\x00\x00\x00\x00WEBPVP8 "


def test_get_image_type_accepts_headers_shorter_than_12_bytes():
    """Magic-byte probes use slices, so a valid short header must be detected."""
    assert get_image_type(PNG_SIGNATURE) == "png"
    assert get_image_type(GIF_HEADER) == "gif"
    assert get_image_type(JPEG_SOI[:3]) == "jpeg"
    assert get_image_type(JPEG_SOI) == "jpeg"


def test_get_image_type_still_detects_webp_and_rejects_noise():
    assert get_image_type(WEBP_RIFF) == "webp"
    assert get_image_type(b"") is None
    assert get_image_type(b"not an image") is None


def test_resolve_image_mime_type_uses_short_png_header():
    """Before the fix this fell through to the image/jpeg default."""
    assert resolve_image_mime_type(image_bytes=PNG_SIGNATURE) == "image/png"
