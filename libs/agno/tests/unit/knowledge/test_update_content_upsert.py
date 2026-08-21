"""Pin behavior of Knowledge._update_content / _aupdate_content after the
upsert refactor:

- Existing row -> partial patch must merge metadata (incl. ``_agno`` key) and
  leave untouched fields alone.
- Missing row -> must fall through to upsert (insert path) instead of bailing.
"""

import os
import tempfile

import pytest

from agno.db.sqlite import SqliteDb
from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.knowledge import Knowledge


@pytest.fixture
def knowledge():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SqliteDb(db_file=path)
    k = Knowledge(contents_db=db)
    yield k
    if db.db_engine is not None:
        db.db_engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


def test_existing_row_partial_patch_merges_metadata(knowledge: Knowledge):
    seed = Content(
        id="abc",
        name="doc",
        description="desc",
        metadata={"a": 1, "_agno": {"source": "seed"}},
        status=ContentStatus.PROCESSING,
    )
    knowledge._update_content(seed)

    patch = Content(
        id="abc",
        status=ContentStatus.COMPLETED,
        metadata={"b": 2, "_agno": {"checksum": "deadbeef"}},
    )
    out = knowledge._update_content(patch)

    assert out is not None
    assert out["status"] == "completed"
    assert out["name"] == "doc"
    assert out["description"] == "desc"

    merged = out["metadata"]
    assert merged["a"] == 1
    assert merged["b"] == 2
    assert merged["_agno"] == {"source": "seed", "checksum": "deadbeef"}


def test_missing_row_falls_through_to_upsert(knowledge: Knowledge):
    ghost = Content(
        id="missing-id",
        name="ghost",
        description="appears via upsert",
        status=ContentStatus.FAILED,
        status_message="initial failure",
    )

    out = knowledge._update_content(ghost)

    assert out is not None
    assert out["id"] == "missing-id"
    assert out["status"] == "failed"
    assert out["status_message"] == "initial failure"

    roundtrip = knowledge.contents_db.get_knowledge_content("missing-id")  # type: ignore[union-attr]
    assert roundtrip is not None
    assert roundtrip.status == "failed"
    assert roundtrip.name == "ghost"


def test_update_without_id_returns_none(knowledge: Knowledge):
    out = knowledge._update_content(Content(name="no-id", description="d"))
    assert out is None


@pytest.mark.asyncio
async def test_async_existing_row_partial_patch(knowledge: Knowledge):
    seed = Content(id="zzz", name="n", description="d", metadata={"x": 1})
    await knowledge._aupdate_content(seed)

    patch = Content(id="zzz", status=ContentStatus.COMPLETED, metadata={"y": 2})
    out = await knowledge._aupdate_content(patch)

    assert out is not None
    assert out["status"] == "completed"
    assert out["metadata"] == {"x": 1, "y": 2}


@pytest.mark.asyncio
async def test_async_missing_row_falls_through_to_upsert(knowledge: Knowledge):
    ghost = Content(
        id="async-ghost",
        name="g",
        description="d",
        status=ContentStatus.FAILED,
    )
    out = await knowledge._aupdate_content(ghost)

    assert out is not None
    assert out["status"] == "failed"
    roundtrip = knowledge.contents_db.get_knowledge_content("async-ghost")  # type: ignore[union-attr]
    assert roundtrip is not None
    assert roundtrip.status == "failed"
