"""Tests for the Memories schema's framework-owned per-memory timestamps."""

from agno.learn.schemas import Memories


class TestAddMemory:
    def test_stamps_created_and_updated(self):
        m = Memories(user_id="u1")
        mid = m.add_memory("likes Python")
        entry = m.memories[0]
        assert entry["id"] == mid
        assert entry["content"] == "likes Python"
        # Both timestamps are stamped and equal on insert.
        assert entry["created_at"].endswith("Z")
        assert entry["created_at"] == entry["updated_at"]

    def test_keeps_extra_kwargs(self):
        m = Memories(user_id="u1")
        m.add_memory("likes Python", source="chat", added_by_agent="ag1")
        entry = m.memories[0]
        assert entry["source"] == "chat"
        assert entry["added_by_agent"] == "ag1"

    def test_caller_cannot_override_reserved_fields(self):
        # The model / caller must not be able to set the id or timestamps.
        m = Memories(user_id="u1")
        mid = m.add_memory("x", id="HACK", created_at="1999-01-01", updated_at="1999-01-01")
        entry = m.memories[0]
        assert entry["id"] == mid != "HACK"
        assert entry["created_at"] != "1999-01-01"
        assert entry["updated_at"] != "1999-01-01"


class TestUpdateMemory:
    def test_bumps_updated_at_and_preserves_created_at(self):
        m = Memories(user_id="u1")
        mid = m.add_memory("likes Python")
        created = m.memories[0]["created_at"]

        assert m.update_memory(mid, "loves Python") is True
        entry = m.memories[0]
        assert entry["content"] == "loves Python"
        assert entry["created_at"] == created
        assert entry["updated_at"] >= created

    def test_caller_cannot_override_created_at_on_update(self):
        m = Memories(user_id="u1")
        mid = m.add_memory("x")
        created = m.memories[0]["created_at"]
        m.update_memory(mid, "y", created_at="1999-01-01")
        assert m.memories[0]["created_at"] == created

    def test_returns_false_when_not_found(self):
        m = Memories(user_id="u1")
        assert m.update_memory("missing", "y") is False
