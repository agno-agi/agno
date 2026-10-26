"""HTTP attachment parsing for sandboxed agents.

JSON ``images``/``files`` items become Image/File objects only through a closed key set; nothing a client
sends can name a service path or a remote reference, and nothing is dropped silently.
"""

import base64

import pytest

from agno.media import Audio, File, Image
from agno.os.routers.agents.sandbox import sandbox_attachments


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_json_items_become_image_and_file_objects_with_their_bytes_and_metadata():
    media = sandbox_attachments(
        images=[{"content": b64(b"png"), "format": "png", "mime_type": "image/png"}],
        files=[{"content": b64(b'{"a": 1}'), "filename": "data.json", "mime_type": "application/json"}],
    )
    (image,), (file,) = media["images"], media["files"]
    assert isinstance(image, Image) and image.content == b"png" and image.mime_type == "image/png"
    assert isinstance(file, File) and file.content == b'{"a": 1}' and file.filename == "data.json"


def test_uploaded_objects_pass_through_and_mix_with_json_items():
    upload = File(content=b"uploaded", filename="u.txt", mime_type="text/plain")
    media = sandbox_attachments(files=[upload, {"content": b64(b"json"), "filename": "j.txt"}])
    assert [file.content for file in media["files"]] == [b"uploaded", b"json"]


@pytest.mark.parametrize("text", ["hello", "TestData", "a,b\n", "caf\u00e9"])
def test_text_files_as_the_client_serializes_them_keep_their_exact_bytes(text):
    # File.to_dict sends text/* content as raw UTF-8 (never base64), so decoding it would reject "hello" and
    # silently turn "TestData", which is also valid base64, into different bytes.
    sent = File(content=text.encode(), filename="t.txt", mime_type="text/plain").to_dict()
    assert sent["content"] == text
    (file,) = sandbox_attachments(files=[sent])["files"]
    assert file.content == text.encode() and file.filename == "t.txt"


def test_non_text_files_and_images_must_still_be_valid_base64():
    (pdf,) = sandbox_attachments(files=[File(content=b"%PDF-1.4", mime_type="application/pdf").to_dict()])["files"]
    assert pdf.content == b"%PDF-1.4"
    with pytest.raises(ValueError, match="base64"):
        sandbox_attachments(files=[{"content": "not base64!", "mime_type": "application/pdf"}])
    with pytest.raises(ValueError, match="base64"):
        sandbox_attachments(files=[{"content": "not base64!"}])
    with pytest.raises(ValueError, match="base64"):
        sandbox_attachments(images=[{"content": "not base64!", "format": "png"}])


def test_no_attachments_is_no_media():
    assert sandbox_attachments() == {}
    assert sandbox_attachments(images=[], files=None) == {}


@pytest.mark.parametrize(
    "item",
    [
        {"content": b64(b"x"), "filepath": "/etc/passwd"},
        {"content": b64(b"x"), "url": "https://example.com/a"},
        {"content": b64(b"x"), "media_reference": "ref"},
        {"content": b64(b"x"), "external": {"bucket": "b"}},
        {"content": b64(b"x"), "unknown": 1},
        {"content": b64(b"x"), "metadata": {"k": "v"}},
        {"filename": "a.txt"},
        {"content": ""},
        {"content": "not base64!"},
        {"content": 5},
        {"content": b64(b"x"), "mime_type": 5},
        "text",
        3,
        None,
    ],
    ids=lambda item: str(item)[:30],
)
def test_files_with_service_paths_remote_references_or_unknown_content_are_rejected(item):
    with pytest.raises(ValueError):
        sandbox_attachments(files=[item])


def test_rejection_never_echoes_the_content():
    secret = b64(b"top secret bytes")
    with pytest.raises(ValueError) as error:
        sandbox_attachments(files=[{"content": secret, "mime_type": "definitely/not-valid"}])
    assert secret not in str(error.value)


def test_images_are_named_by_the_harness_so_a_filename_is_refused_not_ignored():
    with pytest.raises(ValueError, match="filename"):
        sandbox_attachments(images=[{"content": b64(b"png"), "format": "png", "filename": "photo.png"}])


def test_audio_and_video_are_refused():
    with pytest.raises(ValueError, match="images and files"):
        sandbox_attachments(audio=[Audio(content=b"a")])
    with pytest.raises(ValueError, match="images and files"):
        sandbox_attachments(videos=[{"content": b64(b"v")}])


def test_objects_that_would_read_the_service_filesystem_or_a_remote_url_are_refused():
    with pytest.raises(ValueError):
        sandbox_attachments(files=[File(filepath="/etc/passwd")])
    with pytest.raises(ValueError):
        sandbox_attachments(files=[File(url="https://example.com/a.txt")])
    with pytest.raises(ValueError, match="metadata"):
        sandbox_attachments(files=[File(content=b"x", filename="a.txt", metadata={"k": "v"})])
    with pytest.raises(ValueError):
        sandbox_attachments(images=[Image(content=b"")])


def test_a_file_may_use_the_older_name_key_but_not_both_with_different_values():
    assert sandbox_attachments(files=[{"content": b64(b"x"), "name": "n.txt"}])["files"][0].filename == "n.txt"
    with pytest.raises(ValueError, match="filename"):
        sandbox_attachments(files=[{"content": b64(b"x"), "name": "a.txt", "filename": "b.txt"}])


def test_the_generated_media_id_is_accepted_and_ignored():
    assert sandbox_attachments(files=[{"content": b64(b"x"), "filename": "a.txt", "id": "abc"}])["files"]


# --- the raw form fields -----------------------------------------------------------------------
# The generic route has already rebuilt JSON media into objects by the time a sandbox agent is reached,
# silently dropping unknown keys and media references, so the sandbox path validates the raw form.

import json  # noqa: E402

from agno.os.routers.agents.sandbox import request_attachments  # noqa: E402


def test_raw_json_form_fields_are_validated_and_merged_with_uploads():
    upload = Image(content=b"uploaded", format="png")
    media = request_attachments(
        {
            "images": json.dumps([{"content": b64(b"json-image"), "format": "png"}]),
            "input_files": json.dumps([{"content": b64(b"doc"), "filename": "d.txt"}]),
        },
        images=[upload],
    )
    assert [image.content for image in media["images"]] == [b"uploaded", b"json-image"]
    assert [file.filename for file in media["files"]] == ["d.txt"]


@pytest.mark.parametrize(
    "form",
    [
        {"input_files": json.dumps([{"content": b64(b"x"), "media_reference": {"storage_key": "k"}}])},
        {"input_files": json.dumps([{"content": b64(b"x"), "filepath": "/etc/passwd"}])},
        {"input_files": json.dumps([{"content": b64(b"x"), "surprise": True}])},
        {"images": json.dumps([{"content": b64(b"x"), "format": "png", "detail": "high"}])},
        {"input_files": "not json"},
        {"input_files": json.dumps({"content": b64(b"x")})},
        {"input_files": object()},
        {"audio": json.dumps([{"content": b64(b"x")}])},
        {"videos": json.dumps([{"content": b64(b"x")}])},
    ],
    ids=[
        "media-reference",
        "filepath",
        "unknown-key",
        "image-detail",
        "not-json",
        "not-array",
        "not-a-string",
        "audio",
        "videos",
    ],
)
def test_raw_form_fields_that_the_generic_route_would_drop_or_rewrite_are_refused(form):
    with pytest.raises(ValueError):
        request_attachments(form)


def test_unset_form_fields_are_no_attachments():
    assert request_attachments({}) == {}
    assert request_attachments({"images": "", "input_files": "[]", "audio": "[]", "videos": ""}) == {}
