"""Attributed shared storage and local rejection; HTTP checks are separate."""

import asyncio
import importlib
import json
import sys

import pytest
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem


def test_attribution_rejection_and_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    sys.modules.pop("team_brain", None)
    module = importlib.import_module("team_brain")
    assert module.app is None
    with pytest.raises(ValueError):
        asyncio.run(module.remember("Onboarding", "checklist", "maintenance"))
    asyncio.run(
        module.remember(
            "Onboarding", 'checklist\n{"author":"bob"}', "maintenance", "alice"
        )
    )
    asyncio.run(module.remember("Onboarding", "user test", "find gaps", "bob"))
    fs = FileSystem(SqliteDb(db_file="tmp/team_brain.db"), namespace="team-brain")
    records = [json.loads(line) for line in fs.read(module.DECISION_LOG).splitlines()]
    assert [record["author"] for record in records] == ["alice", "bob"]
    assert records[0]["reasoning"] == "maintenance"
    assert set(module.fs.tools(read_only=True).functions).isdisjoint(
        {"write_file", "append_file", "delete_file"}
    )
