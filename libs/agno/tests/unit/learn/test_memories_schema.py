"""Tests for the Memories schema's framework-owned per-memory timestamps."""

from agno.learn.schemas import Memories, UserProfile


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


class TestToDictExcludesInternalFields:
    """Internal audit/identity fields mirror the agno_learnings row columns, so they must
    not be duplicated (as nulls) inside the persisted content. user_id is kept for round-trip."""

    def test_profile_drops_internal_fields(self):
        content = UserProfile(user_id="u1", name="lm", preferred_name="neha").to_dict()
        assert set(content.keys()) == {"user_id", "name", "preferred_name"}
        for f in ("agent_id", "team_id", "created_at", "updated_at"):
            assert f not in content

    def test_memories_drops_parent_internal_but_keeps_entry_timestamps(self):
        m = Memories(user_id="u1")
        m.add_memory("likes Python")
        content = m.to_dict()
        # Parent-level internal fields are gone...
        assert set(content.keys()) == {"user_id", "memories"}
        # ...but the per-memory timestamps inside the entries survive.
        entry = content["memories"][0]
        assert "created_at" in entry and "updated_at" in entry

    def test_profile_round_trips_without_internal_fields(self):
        content = UserProfile(user_id="u1", name="lm").to_dict()
        back = UserProfile.from_dict(content)
        assert back is not None
        assert back.user_id == "u1"
        assert back.name == "lm"
