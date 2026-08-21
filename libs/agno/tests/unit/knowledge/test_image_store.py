"""Unit tests for knowledge image store."""

from pathlib import Path

import pytest

from agno.exceptions import PathSecurityError
from agno.knowledge.image import (
    KnowledgeImageRef,
    LocalKnowledgeImageStore,
    build_image_url,
    build_markdown_image,
    save_image_markdown,
    save_image_url,
)


def test_local_store_save_open_delete(tmp_path: Path):
    store = LocalKnowledgeImageStore(base_dir=str(tmp_path / "images"))
    data = b"fake-png-bytes"
    ref = store.save(content_id="content-abc", data=data, media_type="image/png")

    assert ref.content_id == "content-abc"
    assert ref.image_id.startswith("img-")
    assert ref.media_type == "image/png"
    assert (tmp_path / "images" / "content-abc" / f"{ref.image_id}.png").exists()

    loaded = store.open(ref)
    assert loaded == data

    url = build_image_url(ref)
    assert url == f"/knowledge/images/content-abc/{ref.image_id}"
    assert build_markdown_image(ref) == f"![]({url})"

    store.delete(content_id="content-abc", image_id=ref.image_id)
    assert not list((tmp_path / "images" / "content-abc").glob(f"{ref.image_id}.*"))


def test_save_image_helpers(tmp_path: Path):
    from agno.knowledge.image import set_image_store

    store = LocalKnowledgeImageStore(base_dir=str(tmp_path / "images"))
    set_image_store(store)
    try:
        url = save_image_url(content_id="c1", data=b"png-bytes", media_type="image/png")
        assert url.startswith("/knowledge/images/c1/img-")
        assert not url.endswith(".png")

        md = save_image_markdown(
            content_id="c1",
            data=b"jpg-bytes",
            media_type="image/jpeg",
            alt_text="chart",
        )
        assert md.startswith("![chart](/knowledge/images/c1/img-")
        assert md.endswith(")")
        assert ".jpg)" not in md
    finally:
        set_image_store(None)


def test_local_store_delete_content_dir(tmp_path: Path):
    store = LocalKnowledgeImageStore(base_dir=str(tmp_path / "images"))
    store.save(content_id="c1", data=b"one")
    store.save(content_id="c1", data=b"two")
    store.delete(content_id="c1")
    assert not (tmp_path / "images" / "c1").exists()


def test_local_store_rejects_path_traversal(tmp_path: Path):
    store = LocalKnowledgeImageStore(base_dir=str(tmp_path / "images"))
    with pytest.raises(PathSecurityError):
        store.save(content_id="../escape", data=b"x")


@pytest.mark.asyncio
async def test_local_store_async(tmp_path: Path):
    store = LocalKnowledgeImageStore(base_dir=str(tmp_path / "images"))
    ref = await store.asave(content_id="c1", data=b"async-img")
    data = await store.aopen(KnowledgeImageRef(image_id=ref.image_id, content_id="c1"))
    assert data == b"async-img"
    await store.adelete(content_id="c1")


def test_global_image_store_singleton(tmp_path: Path):
    from agno.knowledge.image import get_image_store, set_image_store

    store = LocalKnowledgeImageStore(base_dir=str(tmp_path / "global-images"))
    set_image_store(store)
    try:
        assert get_image_store() is store
    finally:
        set_image_store(None)
