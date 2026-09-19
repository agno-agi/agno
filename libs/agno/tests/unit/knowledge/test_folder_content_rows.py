"""Folder loads land one contents-db row per file, owned by a folder row.

Each file row's id equals the ``content_id`` its vectors carry, a file whose byte
digest is unchanged refreshes its row without re-reading or re-embedding, a changed
file re-embeds alone, a file that left the folder is deleted, an emptied or
unreadable folder keeps the previously loaded rows, and deleting the folder row
cascades to its file rows and their vectors.

Folders are real temp directories: ``.txt`` and ``.md`` files go through the stock
TextReader/MarkdownReader with no extra dependencies.
"""

import hashlib
import time
from pathlib import Path
from typing import List, Optional, Tuple
from unittest import mock

from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.knowledge.utils import get_agno_metadata

ALPHA_TEXT = "alpha text"
BETA_TEXT = "beta text"
GAMMA_TEXT = "gamma text"

READ_ERROR = "RuntimeError: disk error"


def _kb(tmp_path, vector_db, filename: str = "contents.db") -> Knowledge:
    return Knowledge(name="t", vector_db=vector_db, contents_db=SqliteDb(db_file=str(tmp_path / filename)))


def _make_folder(tmp_path) -> Path:
    """A folder with two top-level files and one nested file."""
    folder = tmp_path / "docs"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text(ALPHA_TEXT)
    (folder / "b.md").write_text(BETA_TEXT)
    (folder / "sub" / "c.txt").write_text(GAMMA_TEXT)
    return folder


def _make_two_file_folder(tmp_path) -> Path:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.txt").write_text(ALPHA_TEXT)
    (folder / "b.md").write_text(BETA_TEXT)
    return folder


def _rows(kb: Knowledge):
    rows, _ = kb.contents_db.get_knowledge_contents()
    return rows


def _folder_row(rows):
    folders = [row for row in rows if get_agno_metadata(row.metadata, "children") is not None]
    assert len(folders) == 1, f"expected exactly one folder row, got {len(folders)}"
    return folders[0]


def _child_rows(rows):
    return {row.id: row for row in rows if get_agno_metadata(row.metadata, "parent_id") is not None}


def _child_by_name(rows, name: str):
    children = [row for row in _child_rows(rows).values() if row.name == name]
    assert len(children) == 1, f"expected exactly one child row named {name}, got {len(children)}"
    return children[0]


def _record_deletes(vector_db) -> List[Tuple[str, Optional[str]]]:
    """Shadow ``delete_by_content_id`` with a recording twin that still declares user_id."""
    deleted: List[Tuple[str, Optional[str]]] = []

    def delete_by_content_id(content_id: str, user_id: Optional[str] = None) -> bool:
        deleted.append((content_id, user_id))
        return True

    vector_db.delete_by_content_id = delete_by_content_id
    return deleted


def _clear_writes(vector_db) -> None:
    vector_db.writes.clear()
    vector_db.inserted_documents.clear()
    vector_db.upserted_documents.clear()


async def _raising_async_read(self, source, name=None, password=None):
    raise RuntimeError("disk error")


def _raising_read(self, source, name=None, password=None):
    raise RuntimeError("disk error")


def _assert_folder_and_children_shape(vector_db, rows, folder: Path) -> None:
    assert len(rows) == 4
    folder_row = _folder_row(rows)
    assert folder_row.name == "docs"
    assert folder_row.status == "completed"
    assert folder_row.status_message == "3 of 3 files loaded"
    assert get_agno_metadata(folder_row.metadata, "source_type") == "folder"
    assert get_agno_metadata(folder_row.metadata, "source_path") == str(folder)

    children = _child_rows(rows)
    child_ids = get_agno_metadata(folder_row.metadata, "children")
    assert sorted(child_ids) == sorted(children.keys())
    assert {child.name for child in children.values()} == {"a.txt", "b.md", "c.txt"}

    # Each file row's id equals the content_id its vectors carry, nested files included
    assert len(vector_db.writes) == 3
    content_id_by_name = {doc.name: doc.content_id for doc in vector_db.inserted_documents}
    for child in children.values():
        assert content_id_by_name[child.name] == child.id
        assert child.status == "completed"
        assert child.metadata["team"] == "docs"
        assert get_agno_metadata(child.metadata, "parent_id") == folder_row.id
        assert get_agno_metadata(child.metadata, "source_type") == "folder"
        assert get_agno_metadata(child.metadata, "content_digest")
        assert get_agno_metadata(child.metadata, "vectors_indexed") is True

    # The digest is the sha256 of the file's bytes and the nested file keeps its full path
    alpha = _child_by_name(rows, "a.txt")
    assert get_agno_metadata(alpha.metadata, "content_digest") == hashlib.sha256(ALPHA_TEXT.encode()).hexdigest()
    nested = _child_by_name(rows, "c.txt")
    assert get_agno_metadata(nested.metadata, "source_path") == str(folder / "sub" / "c.txt")


async def test_folder_ainsert_lands_folder_row_and_file_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_folder(tmp_path)

    await kb.ainsert(path=str(folder), metadata={"team": "docs"})

    _assert_folder_and_children_shape(vector_db, _rows(kb), folder)
    folder_content = await kb.aget_content_by_id(_folder_row(_rows(kb)).id)
    assert folder_content.file_type == "folder"


def test_folder_insert_lands_folder_row_and_file_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_folder(tmp_path)

    kb.insert(path=str(folder), metadata={"team": "docs"})

    _assert_folder_and_children_shape(vector_db, _rows(kb), folder)
    folder_content = kb.get_content_by_id(_folder_row(_rows(kb)).id)
    assert folder_content.file_type == "folder"


async def test_ainsert_unchanged_files_skip_embedding_and_refresh_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_folder(tmp_path)
    await kb.ainsert(path=str(folder))
    first_ids = {row.id for row in _rows(kb)}
    _clear_writes(vector_db)

    future = int(time.time()) + 1000
    with mock.patch("time.time", return_value=float(future)):
        await kb.ainsert(path=str(folder))

    assert vector_db.writes == []
    rows = _rows(kb)
    assert {row.id for row in rows} == first_ids
    assert _folder_row(rows).status_message == "3 of 3 files loaded"
    for child in _child_rows(rows).values():
        assert child.status == "completed"
        assert child.updated_at == future, "unchanged file row did not refresh updated_at"


def test_insert_unchanged_files_skip_embedding(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_folder(tmp_path)
    kb.insert(path=str(folder))
    first_ids = {row.id for row in _rows(kb)}
    _clear_writes(vector_db)

    kb.insert(path=str(folder))

    assert vector_db.writes == []
    assert {row.id for row in _rows(kb)} == first_ids


async def test_ainsert_changed_file_reembeds_only_that_file(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_folder(tmp_path)
    await kb.ainsert(path=str(folder))
    previous = _child_by_name(_rows(kb), "a.txt")
    deleted = _record_deletes(vector_db)
    _clear_writes(vector_db)

    (folder / "a.txt").write_text("alpha text v2")
    await kb.ainsert(path=str(folder))

    assert len(vector_db.writes) == 1
    assert [doc.content_id for doc in vector_db.inserted_documents] == [previous.id]
    changed = _child_by_name(_rows(kb), "a.txt")
    assert changed.id == previous.id, "a changed file keeps its row id"
    assert get_agno_metadata(changed.metadata, "content_digest") == hashlib.sha256(b"alpha text v2").hexdigest()
    # A changed file replaces its chunks wholesale, mirroring the page path
    assert [cid for cid, _ in deleted] == [previous.id]


def test_insert_changed_file_reembeds_only_that_file(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_folder(tmp_path)
    kb.insert(path=str(folder))
    previous = _child_by_name(_rows(kb), "a.txt")
    _clear_writes(vector_db)

    (folder / "a.txt").write_text("alpha text v2")
    kb.insert(path=str(folder))

    assert len(vector_db.writes) == 1
    assert [doc.content_id for doc in vector_db.inserted_documents] == [previous.id]


async def test_ainsert_removed_file_prunes_row_and_new_file_lands(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    await kb.ainsert(path=str(folder))
    removed_id = _child_by_name(_rows(kb), "b.md").id
    deleted = _record_deletes(vector_db)
    _clear_writes(vector_db)

    (folder / "b.md").unlink()
    (folder / "c.txt").write_text(GAMMA_TEXT)
    await kb.ainsert(path=str(folder))

    assert (removed_id, None) in deleted
    rows = _rows(kb)
    assert removed_id not in {row.id for row in rows}
    added = _child_by_name(rows, "c.txt")
    assert added.status == "completed"
    assert [doc.name for doc in vector_db.inserted_documents] == ["c.txt"]
    folder_row = _folder_row(rows)
    children = get_agno_metadata(folder_row.metadata, "children")
    assert removed_id not in children
    assert sorted(children) == sorted(_child_rows(rows).keys())
    assert folder_row.status_message == "2 of 2 files loaded"


def test_insert_removed_file_prunes_row_and_new_file_lands(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    kb.insert(path=str(folder))
    removed_id = _child_by_name(_rows(kb), "b.md").id
    deleted = _record_deletes(vector_db)
    _clear_writes(vector_db)

    (folder / "b.md").unlink()
    (folder / "c.txt").write_text(GAMMA_TEXT)
    kb.insert(path=str(folder))

    assert (removed_id, None) in deleted
    rows = _rows(kb)
    assert removed_id not in {row.id for row in rows}
    assert _child_by_name(rows, "c.txt").status == "completed"
    assert _folder_row(rows).status_message == "2 of 2 files loaded"


async def test_ainsert_failing_file_gets_failed_row_without_aborting_folder(vector_db, tmp_path):
    """A file whose read raises lands a FAILED child row and a failure entry on the
    folder row; the folder itself completes with the failure surfaced."""
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)

    with mock.patch.object(TextReader, "async_read", _raising_async_read):
        await kb.ainsert(path=str(folder))

    rows = _rows(kb)
    failed_child = _child_by_name(rows, "a.txt")
    assert failed_child.status == "failed"
    assert failed_child.status_message == READ_ERROR
    assert get_agno_metadata(failed_child.metadata, "content_digest") is None, "a failed read must not leave a digest"
    healthy_child = _child_by_name(rows, "b.md")
    assert healthy_child.status == "completed"
    assert len(vector_db.writes) == 1, "the failed file must not reach the vector db"
    folder_row = _folder_row(rows)
    assert folder_row.status == "completed"
    assert "1 of 2 files loaded" in folder_row.status_message
    assert str(folder / "a.txt") in folder_row.status_message
    assert get_agno_metadata(folder_row.metadata, "failed") == [{"path": str(folder / "a.txt"), "error": READ_ERROR}]

    # The file comes back on the next run with a healthy reader: FAILED rows retry
    _clear_writes(vector_db)
    await kb.ainsert(path=str(folder))

    rows = _rows(kb)
    retried = _child_by_name(rows, "a.txt")
    assert retried.status == "completed"
    assert [doc.name for doc in vector_db.inserted_documents] == ["a.txt"]
    folder_row = _folder_row(rows)
    assert folder_row.status == "completed"
    assert folder_row.status_message == "2 of 2 files loaded"
    assert get_agno_metadata(folder_row.metadata, "failed") is None


def test_insert_failing_file_gets_failed_row_without_aborting_folder(vector_db, tmp_path):
    """Synchronous twin of the failing-file test above."""
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)

    with mock.patch.object(TextReader, "read", _raising_read):
        kb.insert(path=str(folder))

    rows = _rows(kb)
    failed_child = _child_by_name(rows, "a.txt")
    assert failed_child.status == "failed"
    assert failed_child.status_message == READ_ERROR
    assert _child_by_name(rows, "b.md").status == "completed"
    assert len(vector_db.writes) == 1
    folder_row = _folder_row(rows)
    assert folder_row.status == "completed"
    assert "1 of 2 files loaded" in folder_row.status_message

    _clear_writes(vector_db)
    kb.insert(path=str(folder))

    rows = _rows(kb)
    assert _child_by_name(rows, "a.txt").status == "completed"
    assert [doc.name for doc in vector_db.inserted_documents] == ["a.txt"]
    assert _folder_row(rows).status == "completed"


async def test_ainsert_emptied_folder_keeps_previous_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    await kb.ainsert(path=str(folder))
    first_ids = {row.id for row in _rows(kb)}
    deleted = _record_deletes(vector_db)
    _clear_writes(vector_db)

    (folder / "a.txt").unlink()
    (folder / "b.md").unlink()
    await kb.ainsert(path=str(folder))

    rows = _rows(kb)
    folder_row = _folder_row(rows)
    assert folder_row.status == "failed"
    assert folder_row.status_message == "Folder is empty; previous files kept"
    assert {row.id for row in rows} == first_ids
    assert sorted(get_agno_metadata(folder_row.metadata, "children")) == sorted(_child_rows(rows).keys())
    for child in _child_rows(rows).values():
        assert child.status == "completed"
    assert deleted == [], "an emptied folder must not delete the previous files' vectors"
    assert vector_db.writes == []

    # Restoring the files with the same bytes reconciles without re-embedding
    (folder / "a.txt").write_text(ALPHA_TEXT)
    (folder / "b.md").write_text(BETA_TEXT)
    await kb.ainsert(path=str(folder))

    rows = _rows(kb)
    folder_row = _folder_row(rows)
    assert folder_row.status == "completed"
    assert folder_row.status_message == "2 of 2 files loaded"
    assert {row.id for row in rows} == first_ids
    assert vector_db.writes == []


def test_insert_emptied_folder_keeps_previous_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    kb.insert(path=str(folder))
    first_ids = {row.id for row in _rows(kb)}
    deleted = _record_deletes(vector_db)
    _clear_writes(vector_db)

    (folder / "a.txt").unlink()
    (folder / "b.md").unlink()
    kb.insert(path=str(folder))

    rows = _rows(kb)
    folder_row = _folder_row(rows)
    assert folder_row.status == "failed"
    assert folder_row.status_message == "Folder is empty; previous files kept"
    assert {row.id for row in rows} == first_ids
    assert deleted == []
    assert vector_db.writes == []

    (folder / "a.txt").write_text(ALPHA_TEXT)
    (folder / "b.md").write_text(BETA_TEXT)
    kb.insert(path=str(folder))

    assert _folder_row(_rows(kb)).status == "completed"
    assert vector_db.writes == []


async def test_aremove_folder_row_cascades_to_file_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    await kb.ainsert(path=str(folder))
    rows = _rows(kb)
    folder_id = _folder_row(rows).id
    child_ids = set(_child_rows(rows).keys())
    deleted = _record_deletes(vector_db)

    await kb.aremove_content_by_id(folder_id)

    assert _rows(kb) == []
    deleted_ids = [content_id for content_id, _ in deleted]
    for child_id in child_ids:
        assert deleted_ids.count(child_id) == 1
    assert deleted_ids.count(folder_id) == 1


def test_remove_folder_row_cascades_to_file_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    kb.insert(path=str(folder))
    rows = _rows(kb)
    folder_id = _folder_row(rows).id
    child_ids = set(_child_rows(rows).keys())
    deleted = _record_deletes(vector_db)

    kb.remove_content_by_id(folder_id)

    assert _rows(kb) == []
    deleted_ids = [content_id for content_id, _ in deleted]
    for child_id in child_ids:
        assert deleted_ids.count(child_id) == 1
    assert deleted_ids.count(folder_id) == 1


async def test_aremove_file_row_drops_it_from_parent_children(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    await kb.ainsert(path=str(folder))
    rows = _rows(kb)
    removed_id = _child_by_name(rows, "b.md").id
    kept_id = _child_by_name(rows, "a.txt").id

    await kb.aremove_content_by_id(removed_id)

    rows = _rows(kb)
    assert set(_child_rows(rows).keys()) == {kept_id}
    assert removed_id not in {row.id for row in rows}
    assert get_agno_metadata(_folder_row(rows).metadata, "children") == [kept_id]


async def test_vector_delete_false_keeps_file_row_async(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    await kb.ainsert(path=str(folder))
    child_id = _child_by_name(_rows(kb), "a.txt").id

    vector_db.delete_by_content_id = lambda content_id, user_id=None: False
    removed = await kb.aremove_content_by_id(child_id)

    assert removed is False
    assert await kb.aget_content_by_id(child_id) is not None, "the row must stay while its vectors exist"
    assert child_id in get_agno_metadata(_folder_row(_rows(kb)).metadata, "children")


def test_vector_delete_false_keeps_file_row_sync(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    kb.insert(path=str(folder))
    child_id = _child_by_name(_rows(kb), "a.txt").id

    vector_db.delete_by_content_id = lambda content_id, user_id=None: False
    removed = kb.remove_content_by_id(child_id)

    assert removed is False
    assert kb.get_content_by_id(child_id) is not None


async def test_ainsert_single_file_keeps_single_row(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    single = tmp_path / "solo.txt"
    single.write_text("solo text")

    await kb.ainsert(path=str(single))

    rows = _rows(kb)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "solo.txt"
    assert row.status == "completed"
    assert get_agno_metadata(row.metadata, "children") is None
    assert get_agno_metadata(row.metadata, "parent_id") is None
    assert get_agno_metadata(row.metadata, "vectors_indexed") is True
    assert len(vector_db.writes) == 1
    assert all(doc.content_id == row.id for doc in vector_db.inserted_documents)


def test_insert_single_file_keeps_single_row(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    single = tmp_path / "solo.txt"
    single.write_text("solo text")

    kb.insert(path=str(single))

    rows = _rows(kb)
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert get_agno_metadata(rows[0].metadata, "children") is None
    assert get_agno_metadata(rows[0].metadata, "vectors_indexed") is True
    assert len(vector_db.writes) == 1


async def test_ainsert_scoped_owner_owns_rows_and_vectors(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)

    await kb.ainsert(path=str(folder), user_id="u1")

    rows = _rows(kb)
    assert len(rows) == 3
    assert all(row.user_id == "u1" for row in rows)
    assert vector_db.owners == ["u1", "u1"]

    # The owner's scoped delete of the folder row removes everything
    await kb.aremove_content_by_id(_folder_row(rows).id, user_id="u1")
    assert _rows(kb) == []


async def test_ainsert_exclude_pattern_skips_matching_files(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_two_file_folder(tmp_path)
    (folder / "noise.log").write_text("log line")

    await kb.ainsert(path=str(folder), exclude=["*.log"])

    rows = _rows(kb)
    assert {row.name for row in rows} == {"docs", "a.txt", "b.md"}
    folder_row = _folder_row(rows)
    assert folder_row.status_message == "2 of 2 files loaded"
    assert len(get_agno_metadata(folder_row.metadata, "children")) == 2
    assert len(vector_db.writes) == 2


def test_insert_include_pattern_limits_to_matching_files(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    folder = _make_folder(tmp_path)

    kb.insert(path=str(folder), include=["*.txt"])

    rows = _rows(kb)
    # Basename matching: nested sub/c.txt matches *.txt too
    assert {row.name for row in rows} == {"docs", "a.txt", "c.txt"}
    folder_row = _folder_row(rows)
    assert folder_row.status_message == "2 of 2 files loaded"
    assert len(vector_db.writes) == 2
