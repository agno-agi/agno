"""SDK ingest errors must leave a terminal contents-db row, not 'processing'.

The row is written before any vector work, so an error raised there (here, the
pre-v3 migration gate) must mark the row failed with a reason before re-raising.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock

import pytest

from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge

MIGRATION_ERROR = ValueError(
    "user_id='alice' was passed but table 't' predates per-user isolation and has no "
    "'user_id' column. Run the v2 -> v3 migration."
)


def _knowledge_with_raising_gate():
    db_file = os.path.join(tempfile.mkdtemp(), "contents.db")
    vector_db = MagicMock()
    vector_db.exists.return_value = True
    vector_db.content_hash_exists.side_effect = MIGRATION_ERROR
    knowledge = Knowledge(vector_db=vector_db, contents_db=SqliteDb(db_file=db_file))
    return knowledge, db_file


def _rows(db_file: str):
    conn = sqlite3.connect(db_file)
    try:
        return conn.execute("SELECT name, status, status_message FROM agno_knowledge").fetchall()
    finally:
        conn.close()


def test_async_sdk_ingest_marks_row_failed_and_raises():
    knowledge, db_file = _knowledge_with_raising_gate()

    with pytest.raises(ValueError, match="migration"):
        asyncio.run(knowledge.ainsert(name="alice_doc", text_content="hello", user_id="alice"))

    rows = _rows(db_file)
    assert len(rows) == 1
    name, status, message = rows[0]
    assert name == "alice_doc"
    assert status == "failed", f"row stranded in status={status!r}"
    assert "migration" in (message or ""), f"no reason attached: {message!r}"


def test_sync_sdk_ingest_marks_row_failed_and_raises():
    knowledge, db_file = _knowledge_with_raising_gate()

    with pytest.raises(ValueError, match="migration"):
        knowledge.insert(name="alice_doc", text_content="hello", user_id="alice")

    rows = _rows(db_file)
    assert len(rows) == 1
    _name, status, message = rows[0]
    assert status == "failed", f"row stranded in status={status!r}"
    assert "migration" in (message or "")
