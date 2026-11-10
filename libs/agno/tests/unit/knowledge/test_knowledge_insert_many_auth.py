"""Tests for insert_many() and ainsert_many() auth and user_id parameter passing."""

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, patch

import pytest

from agno.knowledge.content import Content, ContentAuth
from agno.knowledge.remote_content.remote_content import GCSContent


@pytest.fixture
def text_files(tmp_path) -> List[str]:
    paths = []
    for name, body in (("alpha.txt", "alpha document"), ("beta.txt", "beta document")):
        file_path = tmp_path / name
        file_path.write_text(body)
        paths.append(str(file_path))
    return paths


def _origins(knowledge) -> List[Tuple[str, Optional[str]]]:
    """Record (content origin, owner) instead of loading, so the fetching loops need no network."""
    seen: List[Tuple[str, Optional[str]]] = []

    def _record(content: Content, *args, **kwargs) -> None:
        for origin in ("path", "url", "file_data", "topics", "remote_content"):
            if getattr(content, origin, None):
                seen.append((origin, content.user_id))

    async def _arecord(content: Content, *args, **kwargs) -> None:
        _record(content)

    knowledge._load_content = _record  # type: ignore[method-assign]
    knowledge._aload_content = _arecord  # type: ignore[method-assign]
    return seen


def _all_content_kwargs() -> Dict[str, Any]:
    """One item for every loop of the keyword branch."""
    return {
        "paths": ["doc.txt"],
        "urls": ["https://example.com/doc.txt"],
        "text_contents": ["some text"],
        "topics": ["Cats"],
        "remote_content": GCSContent(bucket_name="bucket", blob_name="doc.txt"),
    }


# --- auth ---


def test_insert_many_passes_auth_to_insert(knowledge):
    auth1 = ContentAuth(password="secret1")
    auth2 = ContentAuth(password="secret2")

    with patch.object(knowledge, "insert") as mock_insert:
        knowledge.insert_many(
            [
                {"text_content": "doc1", "auth": auth1},
                {"text_content": "doc2", "auth": auth2},
            ]
        )

        assert mock_insert.call_count == 2
        assert mock_insert.call_args_list[0][1].get("auth") == auth1
        assert mock_insert.call_args_list[1][1].get("auth") == auth2


def test_insert_many_passes_none_auth_when_not_provided(knowledge):
    with patch.object(knowledge, "insert") as mock_insert:
        knowledge.insert_many(
            [
                {"text_content": "doc1"},
                {"text_content": "doc2"},
            ]
        )

        assert mock_insert.call_count == 2
        for call in mock_insert.call_args_list:
            assert call[1].get("auth") is None


@pytest.mark.asyncio
async def test_ainsert_many_passes_auth_to_ainsert(knowledge):
    auth1 = ContentAuth(password="secret1")
    auth2 = ContentAuth(password="secret2")

    with patch.object(knowledge, "ainsert", new_callable=AsyncMock) as mock_ainsert:
        await knowledge.ainsert_many(
            [
                {"text_content": "doc1", "auth": auth1},
                {"text_content": "doc2", "auth": auth2},
            ]
        )

        assert mock_ainsert.call_count == 2
        assert mock_ainsert.call_args_list[0][1].get("auth") == auth1
        assert mock_ainsert.call_args_list[1][1].get("auth") == auth2


@pytest.mark.asyncio
async def test_ainsert_many_passes_none_auth_when_not_provided(knowledge):
    with patch.object(knowledge, "ainsert", new_callable=AsyncMock) as mock_ainsert:
        await knowledge.ainsert_many(
            [
                {"text_content": "doc1"},
                {"text_content": "doc2"},
            ]
        )

        assert mock_ainsert.call_count == 2
        for call in mock_ainsert.call_args_list:
            assert call[1].get("auth") is None


# --- user_id, keyword branch ---


def test_insert_many_keyword_branch_passes_user_id(knowledge, vector_db, text_files):
    knowledge.insert_many(paths=text_files, user_id="alice")

    assert vector_db.owners == ["alice", "alice"]


def test_insert_many_keyword_branch_text_contents_passes_user_id(knowledge, vector_db):
    knowledge.insert_many(text_contents=["one", "two"], user_id="alice")

    assert vector_db.owners == ["alice", "alice"]


def test_insert_many_keyword_branch_covers_every_content_type(knowledge):
    seen = _origins(knowledge)

    knowledge.insert_many(**_all_content_kwargs(), user_id="alice")

    assert seen == [
        ("path", "alice"),
        ("url", "alice"),
        ("file_data", "alice"),
        ("topics", "alice"),
        ("remote_content", "alice"),
    ]


def test_insert_many_keyword_branch_without_user_id_is_unowned(knowledge, vector_db, text_files):
    knowledge.insert_many(paths=text_files)

    assert vector_db.owners == [None, None]


@pytest.mark.asyncio
async def test_ainsert_many_keyword_branch_passes_user_id(knowledge, vector_db, text_files):
    await knowledge.ainsert_many(paths=text_files, user_id="alice")

    assert vector_db.owners == ["alice", "alice"]


@pytest.mark.asyncio
async def test_ainsert_many_keyword_branch_covers_every_content_type(knowledge):
    seen = _origins(knowledge)

    await knowledge.ainsert_many(**_all_content_kwargs(), user_id="alice")

    assert seen == [
        ("path", "alice"),
        ("url", "alice"),
        ("file_data", "alice"),
        ("topics", "alice"),
        ("remote_content", "alice"),
    ]


@pytest.mark.asyncio
async def test_ainsert_many_keyword_branch_without_user_id_is_unowned(knowledge, vector_db, text_files):
    await knowledge.ainsert_many(paths=text_files)

    assert vector_db.owners == [None, None]


# --- user_id, list-of-dicts branch ---


def test_insert_many_list_branch_applies_top_level_user_id(knowledge, vector_db):
    knowledge.insert_many([{"text_content": "one"}, {"text_content": "two"}], user_id="alice")

    assert vector_db.owners == ["alice", "alice"]


def test_insert_many_list_branch_per_item_user_id_wins(knowledge, vector_db):
    knowledge.insert_many(
        [
            {"text_content": "one", "user_id": "bob"},
            {"text_content": "two"},
        ],
        user_id="alice",
    )

    assert vector_db.owners == ["bob", "alice"]


def test_insert_many_list_branch_per_item_user_id_without_top_level(knowledge, vector_db):
    knowledge.insert_many(
        [
            {"text_content": "one", "user_id": "bob"},
            {"text_content": "two"},
        ]
    )

    assert vector_db.owners == ["bob", None]


def test_insert_many_list_branch_without_user_id_is_unowned(knowledge, vector_db):
    knowledge.insert_many([{"text_content": "one"}, {"text_content": "two"}])

    assert vector_db.owners == [None, None]


@pytest.mark.asyncio
async def test_ainsert_many_list_branch_applies_top_level_user_id(knowledge, vector_db):
    await knowledge.ainsert_many([{"text_content": "one"}, {"text_content": "two"}], user_id="alice")

    assert vector_db.owners == ["alice", "alice"]


@pytest.mark.asyncio
async def test_ainsert_many_list_branch_per_item_user_id_wins(knowledge, vector_db):
    await knowledge.ainsert_many(
        [
            {"text_content": "one", "user_id": "bob"},
            {"text_content": "two"},
        ],
        user_id="alice",
    )

    assert vector_db.owners == ["bob", "alice"]


@pytest.mark.asyncio
async def test_ainsert_many_list_branch_without_user_id_is_unowned(knowledge, vector_db):
    await knowledge.ainsert_many([{"text_content": "one"}, {"text_content": "two"}])

    assert vector_db.owners == [None, None]
