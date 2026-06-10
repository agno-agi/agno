"""Tests for framework-owned per-entry timestamps on learning schemas (memories, entity facts...)."""

from agno.learn.schemas import EntityMemory, Memories, UserProfile


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
    """UserProfile drops its internal audit/identity fields from content (they mirror the
    agno_learnings row columns and would always be null). Scoped to UserProfile only;
    Memories keeps its full serialization. user_id is kept for round-trip."""

    def test_profile_drops_internal_fields(self):
        content = UserProfile(user_id="u1", name="lm", preferred_name="neha").to_dict()
        assert set(content.keys()) == {"user_id", "name", "preferred_name"}
        for f in ("agent_id", "team_id", "created_at", "updated_at"):
            assert f not in content

    def test_memories_keeps_parent_fields_and_entry_timestamps(self):
        m = Memories(user_id="u1")
        m.add_memory("likes Python")
        content = m.to_dict()
        # Memories keeps its full serialization (parent internal fields included)...
        assert "created_at" in content and "agent_id" in content
        # ...and the per-memory timestamps inside the entries are present.
        entry = content["memories"][0]
        assert "created_at" in entry and "updated_at" in entry

    def test_profile_round_trips_without_internal_fields(self):
        content = UserProfile(user_id="u1", name="lm").to_dict()
        back = UserProfile.from_dict(content)
        assert back is not None
        assert back.user_id == "u1"
        assert back.name == "lm"


class TestEntityMemoryEntryTimestamps:
    """facts / events / relationships are object-lists inside content; each entry gets
    framework-owned created_at + updated_at, same as memories."""

    def test_add_fact_stamps_timestamps(self):
        e = EntityMemory(entity_id="acme", entity_type="company")
        fid = e.add_fact("uses PostgreSQL", confidence=0.9)
        fact = e.facts[0]
        assert fact["id"] == fid
        assert fact["created_at"].endswith("Z")
        assert fact["created_at"] == fact["updated_at"]
        assert fact["confidence"] == 0.9

    def test_add_event_and_relationship_stamp_timestamps(self):
        e = EntityMemory(entity_id="acme", entity_type="company")
        e.add_event("launched v2", date="2024-01-15")
        e.add_relationship("bob", "CEO")
        assert e.events[0]["created_at"].endswith("Z")
        assert e.events[0]["date"] == "2024-01-15"
        assert e.relationships[0]["created_at"] == e.relationships[0]["updated_at"]

    def test_add_fact_caller_cannot_override_reserved_fields(self):
        e = EntityMemory(entity_id="acme", entity_type="company")
        fid = e.add_fact("x", id="HACK", created_at="1999-01-01")
        fact = e.facts[0]
        assert fact["id"] == fid != "HACK"
        assert fact["created_at"] != "1999-01-01"

    def test_update_fact_bumps_updated_at_preserves_created_at(self):
        e = EntityMemory(entity_id="acme", entity_type="company")
        fid = e.add_fact("uses PG")
        created = e.facts[0]["created_at"]
        assert e.update_fact(fid, "uses PG 16") is True
        fact = e.facts[0]
        assert fact["content"] == "uses PG 16"
        assert fact["created_at"] == created
        assert fact["updated_at"] >= created
