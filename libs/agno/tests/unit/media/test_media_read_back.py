"""Reading offloaded media back through a storage handle.

Covers ``get_content_bytes(storage=...)`` and ``get_url(storage=...)`` on all four media
classes, the guards that refuse a handle that did not mint the reference, and the fallback
to storage when a url the media also carries cannot be fetched.
"""

import tempfile

import pytest

from agno.media import Audio, File, Image, Video
from agno.media.reference import MediaReference
from agno.media.storage.local import AsyncLocalMediaStorage, LocalMediaStorage

CLASSES = [Image, Audio, Video, File]
CONTENT = b"REAL-BYTES-IN-STORAGE"
DEAD_URL = "http://127.0.0.1:9/gone.png"


@pytest.fixture
def stored():
    """A local backend holding one object, and the reference that names it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        key = storage.upload("m1", CONTENT, mime_type="image/png")
        ref = MediaReference(media_id="m1", storage_key=key, storage_backend="local", bucket=storage.bucket)
        yield storage, ref


@pytest.mark.parametrize("cls", CLASSES)
def test_a_reference_resolves_to_its_bytes(cls, stored):
    storage, ref = stored
    assert cls(id="m1", media_reference=ref).get_content_bytes(storage=storage) == CONTENT


@pytest.mark.parametrize("cls", CLASSES)
@pytest.mark.asyncio
async def test_a_reference_resolves_to_its_bytes_async(cls, stored):
    storage, ref = stored
    media = cls(id="m1", media_reference=ref)
    assert await media.aget_content_bytes(storage=storage) == CONTENT


@pytest.mark.parametrize("cls", CLASSES)
def test_without_a_handle_a_reference_has_no_bytes(cls, stored):
    _, ref = stored
    assert cls(id="m1", media_reference=ref).get_content_bytes() is None


@pytest.mark.parametrize("cls", CLASSES)
def test_a_handle_that_did_not_mint_the_reference_is_refused(cls, stored):
    storage, ref = stored
    with tempfile.TemporaryDirectory() as other_dir:
        other = LocalMediaStorage(base_path=other_dir)
        # The same key exists in the other root, so a bucket-blind read would return its bytes.
        other.upload("m1", b"WRONG-OBJECT", mime_type="image/png")
        assert cls(id="m1", media_reference=ref).get_content_bytes(storage=other) is None


def test_an_async_backend_on_a_sync_call_is_refused(stored):
    _, ref = stored
    with tempfile.TemporaryDirectory() as tmpdir:
        async_storage = AsyncLocalMediaStorage(base_path=tmpdir)
        with pytest.raises(ValueError, match="aget_content_bytes"):
            Image(id="m1", media_reference=ref).get_content_bytes(storage=async_storage)
        with pytest.raises(ValueError, match="aget_url"):
            Image(id="m1", media_reference=ref).get_url(storage=async_storage)


@pytest.mark.asyncio
async def test_a_sync_backend_on_an_async_call_reads_off_the_loop(stored):
    storage, ref = stored
    media = Image(id="m1", media_reference=ref)
    assert await media.aget_content_bytes(storage=storage) == CONTENT


def test_a_url_that_cannot_be_fetched_falls_back_to_the_stored_object(stored):
    storage, ref = stored
    media = Image(id="m1", media_reference=ref, url=DEAD_URL)
    assert media.get_content_bytes(storage=storage) == CONTENT


@pytest.mark.asyncio
async def test_a_url_that_cannot_be_fetched_falls_back_to_the_stored_object_async(stored):
    storage, ref = stored
    media = Image(id="m1", media_reference=ref, url=DEAD_URL)
    assert await media.aget_content_bytes(storage=storage) == CONTENT


def test_a_failing_url_still_raises_without_a_handle_to_fall_back_to():
    """The handle is what makes a fallback possible; without one the fetch error stands."""
    import httpx

    with pytest.raises(httpx.HTTPError):
        Image(id="m1", url=DEAD_URL).get_content_bytes()


def test_a_working_url_is_used_without_touching_storage(stored):
    storage, ref = stored

    class Counting(LocalMediaStorage):
        hits = 0

        def download(self, storage_key):
            Counting.hits += 1
            return super().download(storage_key)

    counting = Counting(base_path=str(storage.base_path))
    media = Image(id="m1", media_reference=ref, url="https://raw.githubusercontent.com/agno-agi/agno/main/README.md")
    assert media.get_content_bytes(storage=counting)
    assert Counting.hits == 0


def test_a_backend_that_cannot_address_a_key_yields_no_url(stored):
    """Local files are not addressable off the machine, so there is no link to hand out."""
    storage, ref = stored
    assert Image(id="m1", media_reference=ref).get_url(storage=storage) is None


def test_media_with_no_reference_yields_no_url(stored):
    storage, _ = stored
    assert Image(id="m1", content=CONTENT).get_url(storage=storage) is None


@pytest.mark.parametrize("cls", CLASSES)
def test_a_url_on_the_reference_is_a_url_both_accessors_agree_on(cls, stored):
    """``get_url`` reports the link ``get_content_bytes`` would fetch, not a different one."""
    storage, ref = stored
    ref = ref.model_copy(update={"url": "https://cdn.example.com/from-reference.png"})
    media = cls(id="m1", media_reference=ref)
    assert media.get_url(storage=storage) == "https://cdn.example.com/from-reference.png"
