import pytest

from agno.utils.media import get_image_type, resolve_image_mime_type


def ftyp(major, *compatible, extended=False):
    payload = major + b"\x00\x00\x00\x00" + b"".join(compatible)
    if extended:
        return b"\x00\x00\x00\x01ftyp" + (16 + len(payload)).to_bytes(8, "big") + payload
    return (8 + len(payload)).to_bytes(4, "big") + b"ftyp" + payload


@pytest.mark.parametrize(
    "data,expected",
    [
        (ftyp(b"avif", b"mif1"), "avif"),
        (ftyp(b"avis", b"msf1"), "avif"),
        (ftyp(b"mif1", b"avif"), "avif"),
        (ftyp(b"avif", extended=True), "avif"),
        (ftyp(b"heic", b"mif1"), "heic"),
        (ftyp(b"mif1", b"heic"), "heic"),
        (ftyp(b"heix"), "heic"),
        (ftyp(b"mif1"), "heif"),
        (ftyp(b"isom", b"mp42"), None),
        (ftyp(b"qt  "), None),
        (ftyp(b"isom") + b"avif", None),
        (b"\x00\x00\x00\x08ftypavif", None),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 4, "png"),
        (b"GIF89a" + b"\x00" * 6, "gif"),
        (b"\xff\xd8\xff" + b"\x00" * 9, "jpeg"),
        (b"RIFF\x00\x00\x00\x00WEBP", "webp"),
    ],
)
def test_detect_image_type(data, expected):
    assert get_image_type(data) == expected


def test_avif_bytes_resolve_to_avif_mime_type():
    assert resolve_image_mime_type(image_bytes=ftyp(b"avif", b"mif1")) == "image/avif"
