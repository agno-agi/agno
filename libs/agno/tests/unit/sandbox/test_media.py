import base64
import os

import pytest

from agno.media import Audio, File, Image
from agno.sandbox.media import MAX_MEDIA_BYTES, MAX_MEDIA_ITEMS, decode_media, encode_media, validate_media


def test_wire_form_is_canonical_and_ignores_ephemeral_media_ids():
    def build():
        return encode_media(
            images=[Image(content=b"png", format="png")], files=[File(content=b"abc", filename="source.py")]
        )

    first, second = build(), build()
    assert first == second
    assert [item["kind"] for item in first] == ["image", "file"]
    assert first[1]["name"] == "source.py" and first[1]["content"] == base64.b64encode(b"abc").decode()
    decoded = decode_media(first)
    assert decoded["images"][0].content == b"png" and decoded["files"][0].content == b"abc"
    assert decoded["files"][0].id == decode_media(second)["files"][0].id
    assert encode_media(images=decoded["images"], files=decoded["files"]) == first


def test_text_file_content_is_utf8_but_image_content_must_be_bytes():
    assert (
        decode_media(encode_media(files=[File(content="héllo", filename="a.txt")]))["files"][0].content
        == "héllo".encode()
    )
    with pytest.raises(ValueError, match="bytes"):
        encode_media(images=[Image.model_construct(content="not-bytes")])


def test_no_media_is_the_empty_wire_and_empty_decode():
    assert encode_media() == [] and encode_media(images=[], files=None) == []
    assert decode_media([]) == {}


@pytest.mark.parametrize(
    "item",
    [
        File(url="https://example.com/a.txt"),
        File(filepath="/tmp/x", url="https://example.com/a.txt"),
        File(external={"bucket": "b"}),
        File.model_construct(media_reference="ref"),
    ],
)
def test_remote_references_are_rejected(item):
    with pytest.raises(ValueError, match="inline bytes"):
        encode_media(files=[item])


@pytest.mark.parametrize("bad", [{"content": "YQ=="}, "text", Audio(content=b"audio"), 3])
def test_only_image_and_file_objects_are_accepted(bad):
    with pytest.raises(ValueError, match="inline bytes"):
        encode_media(files=[bad])
    with pytest.raises(ValueError, match="inline bytes"):
        encode_media(images=[bad])


def test_explicit_regular_local_file_is_read_and_its_host_path_never_crosses_the_wire(tmp_path):
    path = tmp_path / "code.txt"
    path.write_bytes(b"code")
    wire = encode_media(files=[File(filepath=path)])
    assert wire[0]["name"] == "code.txt" and wire[0]["content"] == base64.b64encode(b"code").decode()
    assert str(tmp_path) not in str(wire)


def test_local_file_inputs_must_be_regular_files_and_within_the_limit(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"x")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(OSError):
        encode_media(files=[File(filepath=link)])
    fifo = tmp_path / "fifo.txt"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular"):
        encode_media(files=[File(filepath=fifo)])
    with pytest.raises((ValueError, OSError)):
        encode_media(files=[File(filepath=tmp_path)])
    with pytest.raises(OSError):
        encode_media(files=[File(filepath=tmp_path / "missing.txt")])
    big = tmp_path / "big.bin"
    big.write_bytes(b"a" * (MAX_MEDIA_BYTES + 1))
    with pytest.raises(ValueError, match="512 KiB"):
        encode_media(files=[File(filepath=big)])


def test_count_limit_is_across_images_and_files():
    assert len(encode_media(files=[File(content=b"a", filename=f"{i}.txt") for i in range(MAX_MEDIA_ITEMS)])) == 16
    assert (
        len(
            encode_media(
                images=[Image(content=b"a", format="png") for _ in range(8)],
                files=[File(content=b"a", filename=f"{i}.txt") for i in range(8)],
            )
        )
        == 16
    )
    with pytest.raises(ValueError, match="16"):
        encode_media(
            images=[Image(content=b"a", format="png") for _ in range(8)],
            files=[File(content=b"a", filename=f"{i}.txt") for i in range(9)],
        )


def test_decoded_byte_limit_is_the_request_total_not_per_attachment():
    half = MAX_MEDIA_BYTES // 2
    assert (
        len(encode_media(files=[File(content=b"a" * half, filename="a"), File(content=b"b" * half, filename="b")])) == 2
    )
    with pytest.raises(ValueError, match="512 KiB"):
        encode_media(files=[File(content=b"a" * half, filename="a"), File(content=b"b" * (half + 1), filename="b")])
    with pytest.raises(ValueError, match="512 KiB"):
        encode_media(
            images=[Image(content=b"a" * half, format="png")], files=[File(content=b"b" * (half + 1), filename="b")]
        )


def test_filenames_cannot_traverse_and_collisions_keep_both_attachments():
    wire = encode_media(files=[File(content=b"a", filename="../../etc/passwd")])
    assert "/" not in wire[0]["name"] and ".." not in wire[0]["name"]
    same = encode_media(files=[File(content=b"a", filename="same.txt"), File(content=b"b", filename="same.txt")])
    assert [item["name"] for item in same] == ["same.txt", "same.txt"]
    assert [file.content for file in decode_media(same)["files"]] == [b"a", b"b"]
    assert len({file.id for file in decode_media(same)["files"]}) == 2


@pytest.mark.parametrize(
    "patch",
    [
        {"name": "../bad"},
        {"name": "a/b"},
        {"name": "a\\b"},
        {"name": ""},
        {"name": "x" * 121},
        {"kind": "audio"},
        {"content": "YR=="},
        {"content": "not base64!"},
        {"content": 5},
        {"extra": True},
        {"mime_type": 5},
    ],
)
def test_runtime_validates_the_wire_not_just_the_service(patch):
    wire = {"kind": "file", "name": "a.txt", "content": "YQ=="}
    with pytest.raises(ValueError):
        validate_media([{**wire, **patch}])


@pytest.mark.parametrize("value", [None, {}, "x", [1], [[]]])
def test_wire_must_be_a_list_of_objects(value):
    with pytest.raises(ValueError):
        validate_media(value)


def test_wire_limits_hold_without_the_encoder():
    item = {"kind": "file", "name": "a.txt", "content": base64.b64encode(b"a").decode()}
    validate_media([item] * MAX_MEDIA_ITEMS)
    with pytest.raises(ValueError):
        validate_media([item] * (MAX_MEDIA_ITEMS + 1))
    big = {"kind": "file", "name": "a.txt", "content": base64.b64encode(b"a" * MAX_MEDIA_BYTES).decode()}
    validate_media([big])
    with pytest.raises(ValueError, match="512 KiB"):
        validate_media([big, item])


# --- coordinator admission ---------------------------------------------------------------------


class _Claimed(Exception):
    """Raised by the fake store at the first durable write, so a test can see what reached it."""


def _coordinator():
    from types import SimpleNamespace

    from agno.sandbox.coordinator import SandboxCoordinator

    claims = []

    async def aclaim(**kwargs):
        claims.append(kwargs)
        raise _Claimed

    coordinator = object.__new__(SandboxCoordinator)
    coordinator.store, coordinator.lease_seconds = SimpleNamespace(aclaim=aclaim), 60
    return coordinator, claims


async def _stream(coordinator, **kwargs):
    async for _ in coordinator.astream(
        "session", agent_id="agent", run_id="run", input="hello", sdk="claude", **kwargs
    ):
        pass


@pytest.mark.asyncio
async def test_admitted_attachments_reach_the_prepared_run_input_and_text_only_is_unchanged():
    coordinator, claims = _coordinator()
    with pytest.raises(_Claimed):
        await _stream(
            coordinator, files=[File(content=b"abc", filename="a.txt")], images=[Image(content=b"png", format="png")]
        )
    prepared = claims[0]["prepared_run"]["input"]
    assert [file["content"] for file in prepared["files"]] == [base64.b64encode(b"abc").decode()]
    assert [image["content"] for image in prepared["images"]] == [base64.b64encode(b"png").decode()]
    with pytest.raises(_Claimed):
        await _stream(coordinator)
    text_only = claims[1]["prepared_run"]["input"]
    assert not text_only.get("files") and not text_only.get("images")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"files": [File(url="https://example.com/a.txt")]},
        {"files": [File(content=b"a", filename=f"{i}.txt") for i in range(MAX_MEDIA_ITEMS + 1)]},
        {"files": [File(content=b"a" * (MAX_MEDIA_BYTES + 1), filename="big.bin")]},
        {"images": [Image(url="https://example.com/a.png")]},
    ],
)
async def test_invalid_attachments_are_rejected_before_any_durable_write(kwargs):
    coordinator, claims = _coordinator()
    with pytest.raises(ValueError):
        await _stream(coordinator, **kwargs)
    assert claims == []


@pytest.mark.asyncio
async def test_attachments_count_toward_the_full_runtime_request_limit():
    coordinator, claims = _coordinator()
    full = [File(content=b"a" * MAX_MEDIA_BYTES, filename="full.bin")]
    with pytest.raises(_Claimed):
        await _stream(coordinator, files=full)
    with pytest.raises(ValueError, match="exceeds"):
        await coordinator.arun("session", agent_id="agent", run_id="run", input="x" * 400_000, sdk="claude", files=full)
    assert len(claims) == 1


def test_sync_run_forwards_attachments():
    coordinator, _ = _coordinator()
    seen = {}

    def sync(function, *args, **kwargs):
        seen.update(kwargs)
        return "ok"

    coordinator.store._sync = sync
    files = [File(content=b"a", filename="a.txt")]
    assert coordinator.run("session", agent_id="agent", run_id="run", input="hello", sdk="claude", files=files) == "ok"
    assert seen["files"] == files


def test_sync_stream_forwards_attachments_through_the_same_admission():
    coordinator, claims = _coordinator()
    coordinator.store.db = object()
    files = [File(content=b"abc", filename="a.txt")]
    with pytest.raises(_Claimed):
        list(coordinator.stream("session", agent_id="agent", run_id="run", input="hello", sdk="claude", files=files))
    assert [file["content"] for file in claims[0]["prepared_run"]["input"]["files"]] == [
        base64.b64encode(b"abc").decode()
    ]
    with pytest.raises(ValueError):
        list(
            coordinator.stream(
                "session",
                agent_id="agent",
                run_id="run",
                input="hello",
                sdk="claude",
                files=[File(url="https://example.com/a.txt")],
            )
        )
    assert len(claims) == 1


def _staged_names(tmp_path, wire):
    from agno.agents._media import stage_media

    return [item.name for item in stage_media(tmp_path / "workspace", "run", decode_media(wire))]


def test_local_image_without_format_is_staged_under_its_file_extension(tmp_path):
    path = tmp_path / "diagram.PNG"
    path.write_bytes(b"not a real png")
    wire = encode_media(images=[Image(filepath=str(path))])
    assert _staged_names(tmp_path, wire) == ["image-1.png"]
    assert encode_media(images=decode_media(wire)["images"]) == wire


@pytest.mark.parametrize(
    "content, extension",
    [
        (b"\x89PNG\r\n\x1a\nrest", "png"),
        (b"\xff\xd8\xffrest", "jpg"),
        (b"GIF89arest", "gif"),
        (b"RIFF\x00\x00\x00\x00WEBPrest", "webp"),
        (b"unknown", "bin"),
    ],
)
def test_inline_image_without_format_is_staged_under_its_signature_extension(tmp_path, content, extension):
    wire = encode_media(images=[Image(content=content)])
    assert _staged_names(tmp_path, wire) == ["image-1." + extension]
    assert encode_media(images=decode_media(wire)["images"]) == wire


def test_file_with_an_image_type_is_rejected_with_a_clear_message():
    with pytest.raises(ValueError, match="images="):
        encode_media(files=[File(content=b"png", format="png")])
    wire = [{"kind": "file", "content": base64.b64encode(b"png").decode(), "name": "a.png", "mime_type": "image/png"}]
    with pytest.raises(ValueError, match="images="):
        validate_media(wire)
