"""Tests for the owner scope of the ``skip_if_exists`` existence check."""

import pytest


@pytest.fixture
def handbook(tmp_path) -> str:
    """One file, so both owners' uploads share a content hash."""
    file_path = tmp_path / "handbook.txt"
    file_path.write_text("the company handbook")
    return str(file_path)


@pytest.fixture
def handbook_dir(tmp_path) -> str:
    directory = tmp_path / "docs"
    directory.mkdir()
    (directory / "handbook.txt").write_text("the company handbook")
    (directory / "policies.txt").write_text("the company policies")
    return str(directory)


# --- Second owner gets their own copy ---


def test_second_owner_gets_own_copy(knowledge, vector_db, handbook):
    """Bob uploading the file Alice already uploaded gets his own chunks."""
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="alice")
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="bob")

    assert vector_db.owners == ["alice", "bob"]


@pytest.mark.asyncio
async def test_second_owner_gets_own_copy_async(knowledge, vector_db, handbook):
    await knowledge.ainsert(path=handbook, skip_if_exists=True, user_id="alice")
    await knowledge.ainsert(path=handbook, skip_if_exists=True, user_id="bob")

    assert vector_db.owners == ["alice", "bob"]


def test_second_owner_gets_own_copy_from_text_content(knowledge, vector_db):
    """The file_data loop takes the same owner as the path loop."""
    knowledge.insert(text_content="the company handbook", skip_if_exists=True, user_id="alice")
    knowledge.insert(text_content="the company handbook", skip_if_exists=True, user_id="bob")

    assert vector_db.owners == ["alice", "bob"]


def test_second_owner_gets_own_copy_from_directory(knowledge, vector_db, handbook_dir):
    """A directory fans out into a Content per file; each one keeps the owner."""
    knowledge.insert(path=handbook_dir, skip_if_exists=True, user_id="alice")
    knowledge.insert(path=handbook_dir, skip_if_exists=True, user_id="bob")

    assert vector_db.owners == ["alice", "alice", "bob", "bob"]


# --- skip_if_exists dedupe within one owner ---


def test_same_owner_second_upload_is_skipped(knowledge, vector_db, handbook):
    """The dedupe still fires within one owner."""
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="alice")
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="alice")

    assert vector_db.owners == ["alice"]


@pytest.mark.asyncio
async def test_same_owner_second_upload_is_skipped_async(knowledge, vector_db, handbook):
    await knowledge.ainsert(path=handbook, skip_if_exists=True, user_id="alice")
    await knowledge.ainsert(path=handbook, skip_if_exists=True, user_id="alice")

    assert vector_db.owners == ["alice"]


def test_unscoped_duplicate_is_still_skipped(knowledge, vector_db, handbook):
    """Deployments that never pass a user_id keep the pre-isolation behaviour."""
    knowledge.insert(path=handbook, skip_if_exists=True)
    knowledge.insert(path=handbook, skip_if_exists=True)

    assert vector_db.owners == [None]


def test_without_skip_if_exists_both_uploads_are_written(knowledge, vector_db, handbook):
    knowledge.insert(path=handbook, user_id="alice")
    knowledge.insert(path=handbook, user_id="alice")

    assert vector_db.owners == ["alice", "alice"]


# --- Owner reaches the existence check ---


def test_owner_reaches_the_existence_check(knowledge, vector_db, handbook):
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="alice")

    assert vector_db.exists_calls
    assert {owner for _, owner in vector_db.exists_calls} == {"alice"}


def test_topics_owner_reaches_the_existence_check(knowledge, vector_db):
    """The topics loop rebuilds Content per topic; the owner has to survive that rebuild."""
    knowledge.insert(topics=["Cats"], skip_if_exists=True, user_id="alice")

    assert vector_db.exists_calls
    assert {owner for _, owner in vector_db.exists_calls} == {"alice"}


@pytest.mark.asyncio
async def test_topics_owner_reaches_the_existence_check_async(knowledge, vector_db):
    await knowledge.ainsert(topics=["Cats"], skip_if_exists=True, user_id="alice")

    assert vector_db.exists_calls
    assert {owner for _, owner in vector_db.exists_calls} == {"alice"}


def test_unscoped_upload_reaches_the_existence_check_with_no_owner(knowledge, vector_db, handbook):
    knowledge.insert(path=handbook, skip_if_exists=True)

    assert vector_db.exists_calls == [(vector_db.exists_calls[0][0], None)]
