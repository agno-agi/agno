"""Deterministic SQLite notes and optional tutorial parity checks."""

import hashlib
import re
from pathlib import Path

import pytest
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem


def test_tutorial_snapshot():
    root = Path(__file__).parent
    expected = re.search(
        r"Extracted Python SHA-256: `([a-f0-9]+)`",
        (root / "TUTORIAL_PARITY.md").read_text(),
    )[1]
    assert (
        hashlib.sha256((root / "personal_agent.py").read_bytes()).hexdigest()
        == expected
    )


def test_durable_notes_and_isolation(tmp_path):
    path = str(tmp_path / "notes.db")
    fs = FileSystem(SqliteDb(db_file=path), namespace="personal-agent/{user_id}")
    alice = fs.resolve(user_id="alice")
    alice.write(
        "onboarding.md",
        "Draft sent to Jen. Test Friday. Checklist: easier to maintain.",
    )
    restarted = FileSystem(SqliteDb(db_file=path), namespace="personal-agent/{user_id}")
    assert "Test Friday" in restarted.resolve(user_id="alice").read("onboarding.md")
    assert restarted.resolve(user_id="bob").list() == []
    with pytest.raises(Exception):
        restarted.resolve().list()
