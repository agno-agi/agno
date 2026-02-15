"""Tests for learning-sourced memories in the memory router.

Tests that user_memory and user_profile data from the learnings table
is surfaced through the /memories endpoints.
"""

import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import AsyncBaseDb
from agno.memory import UserMemory
from agno.os.routers.memory.memory import (
    LM_MEM_PREFIX,
    LM_PROFILE_PREFIX,
    _format_profile_as_memory,
    _get_learning_memories,
    _get_learning_memory_by_id,
    _is_learning_memory_id,
    attach_routes,
)
from agno.os.routers.memory.schemas import UserMemorySchema

# ---------------------------------------------------------------------------
# Dummy async DB with learning support
# ---------------------------------------------------------------------------


class DummyAsyncDb(AsyncBaseDb):
    """Minimal async DB implementation for testing learning memory integration."""

    def __init__(self):
        super().__init__()
        self._memories: Dict[str, Dict[str, UserMemory]] = {}
        self._learnings: Dict[str, Dict[str, Any]] = {}

    # --- Learning helpers for test setup ---

    def seed_learning(self, learning_type: str, user_id: str, content: Dict[str, Any]) -> None:
        """Seed a learning record for testing."""
        key = f"{learning_type}:{user_id}"
        self._learnings[key] = {
            "content": content,
            "updated_at": int(time.time()),
        }

    # --- Learning methods ---

    async def get_learning(
        self, learning_type: str, user_id: Optional[str] = None, **kwargs
    ) -> Optional[Dict[str, Any]]:
        key = f"{learning_type}:{user_id}"
        return self._learnings.get(key)

    async def upsert_learning(
        self, id: str, learning_type: str, content: Dict[str, Any], user_id: Optional[str] = None, **kwargs
    ) -> None:
        key = f"{learning_type}:{user_id}"
        self._learnings[key] = {
            "content": content,
            "updated_at": int(time.time()),
        }

    async def delete_learning(self, id: str, **kwargs) -> bool:
        # Find and remove by matching the id pattern
        to_remove = []
        for key in self._learnings:
            if id.startswith("memories_"):
                uid = id[len("memories_") :]
                if key == f"user_memory:{uid}":
                    to_remove.append(key)
            elif id.startswith("user_profile_"):
                uid = id[len("user_profile_") :]
                if key == f"user_profile:{uid}":
                    to_remove.append(key)
        for key in to_remove:
            del self._learnings[key]
        return len(to_remove) > 0

    async def get_learnings(self, **kwargs) -> List[Dict[str, Any]]:
        return list(self._learnings.values())

    # --- Memory methods (for regular memories) ---

    async def upsert_user_memory(self, memory: UserMemory, deserialize: Optional[bool] = True):
        user_id = memory.user_id or "default"
        user_memories = self._memories.setdefault(user_id, {})
        memory_id = memory.memory_id or f"mem-{len(user_memories) + 1}"
        memory.memory_id = memory_id
        user_memories[memory_id] = memory
        return memory if deserialize else memory.to_dict()

    async def get_user_memory(self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None):
        user = user_id or "default"
        memory = self._memories.get(user, {}).get(memory_id)
        if memory is None:
            # Check all users
            for uid, memories in self._memories.items():
                if memory_id in memories:
                    memory = memories[memory_id]
                    break
        if memory is None:
            return None
        return memory if deserialize else memory.to_dict()

    async def get_user_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, page: Optional[int] = None, **kwargs
    ) -> Tuple[List, int]:
        if user_id:
            memories = list(self._memories.get(user_id, {}).values())
        else:
            memories = [m for mems in self._memories.values() for m in mems.values()]
        dicts = [m.to_dict() for m in memories]
        return dicts, len(dicts)

    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        user = user_id or "default"
        self._memories.get(user, {}).pop(memory_id, None)

    async def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        user = user_id or "default"
        user_memories = self._memories.get(user, {})
        for mid in memory_ids:
            user_memories.pop(mid, None)

    async def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None, user_id: Optional[str] = None
    ) -> Tuple[List[Dict], int]:
        stats: Dict[str, int] = {}
        for uid, memories in self._memories.items():
            if user_id and uid != user_id:
                continue
            stats[uid] = len(memories)
        result = [
            {"user_id": uid, "total_memories": count, "last_memory_updated_at": int(time.time())}
            for uid, count in stats.items()
        ]
        return result, len(result)

    async def get_all_memory_topics(self, *args, **kwargs) -> List[str]:
        return []

    async def clear_memories(self) -> None:
        self._memories.clear()

    # --- Stub methods (not used in these tests) ---

    async def table_exists(self, table_name: str) -> bool:
        return True

    async def delete_session(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_sessions(self, *args, **kwargs):
        raise NotImplementedError

    async def get_session(self, *args, **kwargs):
        raise NotImplementedError

    async def get_sessions(self, *args, **kwargs):
        raise NotImplementedError

    async def rename_session(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_session(self, *args, **kwargs):
        raise NotImplementedError

    async def get_metrics(self, *args, **kwargs):
        raise NotImplementedError

    async def calculate_metrics(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    async def get_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    async def get_knowledge_contents(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_knowledge_content(self, *args, **kwargs):
        raise NotImplementedError

    async def create_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_eval_runs(self, *args, **kwargs):
        raise NotImplementedError

    async def get_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    async def get_eval_runs(self, *args, **kwargs):
        raise NotImplementedError

    async def rename_eval_run(self, *args, **kwargs):
        raise NotImplementedError

    async def clear_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def get_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def get_all_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_cultural_knowledge(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_trace(self, *args, **kwargs):
        raise NotImplementedError

    async def get_trace(self, *args, **kwargs):
        raise NotImplementedError

    async def get_traces(self, *args, **kwargs):
        raise NotImplementedError

    async def get_trace_stats(self, *args, **kwargs):
        raise NotImplementedError

    async def create_span(self, *args, **kwargs):
        raise NotImplementedError

    async def create_spans(self, *args, **kwargs):
        raise NotImplementedError

    async def get_span(self, *args, **kwargs):
        raise NotImplementedError

    async def get_spans(self, *args, **kwargs):
        raise NotImplementedError

    async def get_latest_schema_version(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_schema_version(self, *args, **kwargs):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    return DummyAsyncDb()


@pytest.fixture
def db_with_learnings(db: DummyAsyncDb) -> DummyAsyncDb:
    """DB seeded with user_memory and user_profile learnings."""
    db.seed_learning(
        learning_type="user_memory",
        user_id="alice",
        content={
            "user_id": "alice",
            "memories": [
                {"id": "abc123", "content": "Likes Python"},
                {"id": "def456", "content": "Works at Anthropic"},
                {"id": "ghi789", "content": "Prefers dark mode"},
            ],
        },
    )
    db.seed_learning(
        learning_type="user_profile",
        user_id="alice",
        content={
            "user_id": "alice",
            "name": "Alice Smith",
            "preferred_name": "Alice",
            "role": "Software Engineer",
        },
    )
    return db


@pytest.fixture
def test_client(db_with_learnings: DummyAsyncDb) -> TestClient:
    """Create a FastAPI test client with the memory router."""
    from fastapi.routing import APIRouter

    app = FastAPI()
    router = APIRouter()
    dbs = {"default": [db_with_learnings]}
    attach_routes(router=router, dbs=dbs)
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestIsLearningMemoryId:
    def test_lm_mem_prefix(self):
        assert _is_learning_memory_id("lm_mem_abc123") is True

    def test_lm_profile_prefix(self):
        assert _is_learning_memory_id("lm_profile_alice") is True

    def test_regular_uuid(self):
        assert _is_learning_memory_id("f9361a69-2997-40c7-ae4e-a5861d434047") is False

    def test_empty_string(self):
        assert _is_learning_memory_id("") is False

    def test_partial_prefix(self):
        assert _is_learning_memory_id("lm_me") is False
        assert _is_learning_memory_id("lm_prof") is False


class TestFormatProfileAsMemory:
    def test_formats_profile_fields(self):
        content = {
            "user_id": "alice",
            "name": "Alice Smith",
            "preferred_name": "Alice",
            "role": "Engineer",
        }
        result = _format_profile_as_memory(content, "alice", None)
        assert result is not None
        assert result.memory_id == f"{LM_PROFILE_PREFIX}alice"
        assert "Name: Alice Smith" in result.memory
        assert "Preferred Name: Alice" in result.memory
        assert "Role: Engineer" in result.memory
        assert result.topics == ["user_profile"]
        assert result.user_id == "alice"

    def test_skips_internal_fields(self):
        content = {
            "user_id": "alice",
            "agent_id": "agent-1",
            "team_id": "team-1",
            "created_at": 12345,
            "updated_at": 12345,
            "name": "Alice",
        }
        result = _format_profile_as_memory(content, "alice", None)
        assert result is not None
        # Only "name" should appear, internal fields are skipped
        assert "Name: Alice" in result.memory
        assert "Agent Id" not in result.memory
        assert "User Id" not in result.memory

    def test_skips_none_values(self):
        content = {
            "user_id": "alice",
            "name": "Alice",
            "preferred_name": None,
        }
        result = _format_profile_as_memory(content, "alice", None)
        assert result is not None
        assert "Preferred Name" not in result.memory

    def test_returns_none_for_empty_profile(self):
        content = {"user_id": "alice"}
        result = _format_profile_as_memory(content, "alice", None)
        assert result is None

    def test_returns_none_for_all_none_values(self):
        content = {"user_id": "alice", "name": None, "role": None}
        result = _format_profile_as_memory(content, "alice", None)
        assert result is None


# ---------------------------------------------------------------------------
# Async unit tests for helper functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetLearningMemories:
    async def test_returns_user_memory_entries(self, db_with_learnings: DummyAsyncDb):
        results = await _get_learning_memories(db_with_learnings, "alice")
        mem_entries = [m for m in results if m.memory_id.startswith(LM_MEM_PREFIX)]
        assert len(mem_entries) == 3
        assert any("Likes Python" in m.memory for m in mem_entries)
        assert any("Works at Anthropic" in m.memory for m in mem_entries)
        assert any("Prefers dark mode" in m.memory for m in mem_entries)

    async def test_returns_user_profile_entry(self, db_with_learnings: DummyAsyncDb):
        results = await _get_learning_memories(db_with_learnings, "alice")
        profile_entries = [m for m in results if m.memory_id.startswith(LM_PROFILE_PREFIX)]
        assert len(profile_entries) == 1
        assert "Alice Smith" in profile_entries[0].memory
        assert profile_entries[0].topics == ["user_profile"]

    async def test_returns_empty_for_unknown_user(self, db_with_learnings: DummyAsyncDb):
        results = await _get_learning_memories(db_with_learnings, "unknown_user")
        assert results == []

    async def test_returns_empty_when_no_learnings(self, db: DummyAsyncDb):
        results = await _get_learning_memories(db, "alice")
        assert results == []

    async def test_memory_ids_have_correct_prefix(self, db_with_learnings: DummyAsyncDb):
        results = await _get_learning_memories(db_with_learnings, "alice")
        for m in results:
            assert m.memory_id.startswith(LM_MEM_PREFIX) or m.memory_id.startswith(LM_PROFILE_PREFIX)

    async def test_all_entries_have_user_id(self, db_with_learnings: DummyAsyncDb):
        results = await _get_learning_memories(db_with_learnings, "alice")
        for m in results:
            assert m.user_id == "alice"


@pytest.mark.asyncio
class TestGetLearningMemoryById:
    async def test_get_user_memory_by_id(self, db_with_learnings: DummyAsyncDb):
        result = await _get_learning_memory_by_id(db_with_learnings, f"{LM_MEM_PREFIX}abc123", "alice")
        assert result.memory == "Likes Python"
        assert result.memory_id == f"{LM_MEM_PREFIX}abc123"
        assert result.user_id == "alice"
        assert result.topics == ["user_memory"]

    async def test_get_profile_by_id(self, db_with_learnings: DummyAsyncDb):
        result = await _get_learning_memory_by_id(db_with_learnings, f"{LM_PROFILE_PREFIX}alice", "alice")
        assert "Alice Smith" in result.memory
        assert result.memory_id == f"{LM_PROFILE_PREFIX}alice"
        assert result.topics == ["user_profile"]

    async def test_not_found_raises_404(self, db_with_learnings: DummyAsyncDb):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _get_learning_memory_by_id(db_with_learnings, f"{LM_MEM_PREFIX}nonexistent", "alice")
        assert exc_info.value.status_code == 404

    async def test_unknown_user_raises_404(self, db_with_learnings: DummyAsyncDb):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _get_learning_memory_by_id(db_with_learnings, f"{LM_MEM_PREFIX}abc123", "unknown_user")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Integration tests via FastAPI TestClient
# ---------------------------------------------------------------------------


class TestGetMemoriesEndpoint:
    def test_learning_memories_included_on_page_1(self, test_client: TestClient):
        response = test_client.get("/memories?user_id=alice")
        assert response.status_code == 200
        data = response.json()
        memories = data["data"]

        # Should include 3 user_memory + 1 user_profile = 4 learning memories
        lm_memories = [m for m in memories if m["memory_id"].startswith("lm_")]
        assert len(lm_memories) == 4

    def test_learning_memories_not_included_on_page_2(self, test_client: TestClient):
        response = test_client.get("/memories?user_id=alice&page=2")
        assert response.status_code == 200
        data = response.json()
        memories = data["data"]
        lm_memories = [m for m in memories if m["memory_id"].startswith("lm_")]
        assert len(lm_memories) == 0

    def test_learning_memories_not_included_without_user_id(self, test_client: TestClient):
        response = test_client.get("/memories")
        assert response.status_code == 200
        data = response.json()
        memories = data["data"]
        lm_memories = [m for m in memories if m["memory_id"].startswith("lm_")]
        assert len(lm_memories) == 0

    def test_search_content_filters_learning_memories(self, test_client: TestClient):
        response = test_client.get("/memories?user_id=alice&search_content=Python")
        assert response.status_code == 200
        data = response.json()
        lm_memories = [m for m in data["data"] if m["memory_id"].startswith("lm_")]
        assert len(lm_memories) == 1
        assert "Python" in lm_memories[0]["memory"]

    def test_topics_filter_learning_memories(self, test_client: TestClient):
        response = test_client.get("/memories?user_id=alice&topics=user_profile")
        assert response.status_code == 200
        data = response.json()
        lm_memories = [m for m in data["data"] if m["memory_id"].startswith("lm_")]
        assert len(lm_memories) == 1
        assert lm_memories[0]["topics"] == ["user_profile"]

    def test_total_count_includes_learning_memories(self, test_client: TestClient):
        response = test_client.get("/memories?user_id=alice")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total_count"] == 4  # 0 regular + 4 learning


class TestGetMemoryByIdEndpoint:
    def test_get_learning_memory_by_id(self, test_client: TestClient):
        response = test_client.get(f"/memories/{LM_MEM_PREFIX}abc123?user_id=alice")
        assert response.status_code == 200
        data = response.json()
        assert data["memory"] == "Likes Python"
        assert data["memory_id"] == f"{LM_MEM_PREFIX}abc123"
        assert data["topics"] == ["user_memory"]

    def test_get_learning_profile_by_id(self, test_client: TestClient):
        response = test_client.get(f"/memories/{LM_PROFILE_PREFIX}alice?user_id=alice")
        assert response.status_code == 200
        data = response.json()
        assert "Alice Smith" in data["memory"]
        assert data["topics"] == ["user_profile"]

    def test_get_nonexistent_learning_memory(self, test_client: TestClient):
        response = test_client.get(f"/memories/{LM_MEM_PREFIX}nonexistent?user_id=alice")
        assert response.status_code == 404


class TestDeleteMemoryEndpoint:
    def test_delete_learning_memory(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        # Verify it exists
        response = test_client.get(f"/memories/{LM_MEM_PREFIX}abc123?user_id=alice")
        assert response.status_code == 200

        # Delete it
        response = test_client.delete(f"/memories/{LM_MEM_PREFIX}abc123?user_id=alice")
        assert response.status_code == 204

        # Verify remaining memories still exist
        response = test_client.get(f"/memories/{LM_MEM_PREFIX}def456?user_id=alice")
        assert response.status_code == 200

    def test_delete_learning_profile(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        response = test_client.delete(f"/memories/{LM_PROFILE_PREFIX}alice?user_id=alice")
        assert response.status_code == 204

        # Verify profile is gone
        response = test_client.get(f"/memories/{LM_PROFILE_PREFIX}alice?user_id=alice")
        assert response.status_code == 404

    def test_delete_nonexistent_learning_memory(self, test_client: TestClient):
        response = test_client.delete(f"/memories/{LM_MEM_PREFIX}nonexistent?user_id=alice")
        assert response.status_code == 404


class TestDeleteMemoriesBatchEndpoint:
    def test_batch_delete_mixed_ids(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        # Create a regular memory first
        response = test_client.post(
            "/memories",
            json={"memory": "Regular memory", "user_id": "alice"},
        )
        assert response.status_code == 200
        regular_id = response.json()["memory_id"]

        # Batch delete both regular and learning memories
        response = test_client.request(
            "DELETE",
            "/memories",
            json={
                "memory_ids": [regular_id, f"{LM_MEM_PREFIX}abc123"],
                "user_id": "alice",
            },
        )
        assert response.status_code == 204

    def test_batch_delete_only_learning_ids(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        response = test_client.request(
            "DELETE",
            "/memories",
            json={
                "memory_ids": [f"{LM_MEM_PREFIX}abc123", f"{LM_MEM_PREFIX}def456"],
                "user_id": "alice",
            },
        )
        assert response.status_code == 204

    def test_batch_delete_nonexistent_learning_ids_silent(self, test_client: TestClient):
        # Non-existent lm_ IDs should be silently skipped
        response = test_client.request(
            "DELETE",
            "/memories",
            json={
                "memory_ids": [f"{LM_MEM_PREFIX}nonexistent"],
                "user_id": "alice",
            },
        )
        assert response.status_code == 204


class TestUpdateMemoryEndpoint:
    def test_update_learning_memory(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        response = test_client.patch(
            f"/memories/{LM_MEM_PREFIX}abc123",
            json={"memory": "Loves Python and Rust", "user_id": "alice"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["memory"] == "Loves Python and Rust"
        assert data["memory_id"] == f"{LM_MEM_PREFIX}abc123"
        assert data["topics"] == ["user_memory"]

    def test_update_learning_memory_persists(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        # Update
        test_client.patch(
            f"/memories/{LM_MEM_PREFIX}abc123",
            json={"memory": "Updated content", "user_id": "alice"},
        )
        # Verify via GET
        response = test_client.get(f"/memories/{LM_MEM_PREFIX}abc123?user_id=alice")
        assert response.status_code == 200
        assert response.json()["memory"] == "Updated content"

    def test_update_profile_returns_400(self, test_client: TestClient):
        response = test_client.patch(
            f"/memories/{LM_PROFILE_PREFIX}alice",
            json={"memory": "New profile", "user_id": "alice"},
        )
        assert response.status_code == 400
        assert "profile" in response.json()["detail"].lower()

    def test_update_nonexistent_learning_memory(self, test_client: TestClient):
        response = test_client.patch(
            f"/memories/{LM_MEM_PREFIX}nonexistent",
            json={"memory": "Something", "user_id": "alice"},
        )
        assert response.status_code == 404


class TestUserMemoryStatsEndpoint:
    def test_stats_include_learning_counts(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        # Create a regular memory
        test_client.post(
            "/memories",
            json={"memory": "Regular memory", "user_id": "alice"},
        )

        response = test_client.get("/user_memory_stats?user_id=alice")
        assert response.status_code == 200
        data = response.json()
        stats = data["data"]
        assert len(stats) == 1
        # 1 regular + 4 learning = 5 total
        assert stats[0]["total_memories"] == 5
        assert stats[0]["user_id"] == "alice"

    def test_stats_for_user_with_only_learnings(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        response = test_client.get("/user_memory_stats?user_id=alice")
        assert response.status_code == 200
        data = response.json()
        stats = data["data"]
        # User has only learning memories, no regular ones
        assert len(stats) == 1
        assert stats[0]["total_memories"] == 4  # 3 mem + 1 profile
        assert stats[0]["user_id"] == "alice"


class TestMixedMemories:
    """Test that regular and learning memories work together."""

    def test_regular_and_learning_memories_coexist(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        # Create regular memories
        test_client.post("/memories", json={"memory": "Regular 1", "user_id": "alice"})
        test_client.post("/memories", json={"memory": "Regular 2", "user_id": "alice"})

        response = test_client.get("/memories?user_id=alice")
        assert response.status_code == 200
        data = response.json()

        regular = [m for m in data["data"] if not m["memory_id"].startswith("lm_")]
        learning = [m for m in data["data"] if m["memory_id"].startswith("lm_")]

        assert len(regular) == 2
        assert len(learning) == 4  # 3 mem + 1 profile
        assert data["meta"]["total_count"] == 6

    def test_regular_crud_unaffected(self, test_client: TestClient, db_with_learnings: DummyAsyncDb):
        # Create
        resp = test_client.post("/memories", json={"memory": "Test memory", "user_id": "alice"})
        assert resp.status_code == 200
        memory_id = resp.json()["memory_id"]

        # Get by ID
        resp = test_client.get(f"/memories/{memory_id}?user_id=alice")
        assert resp.status_code == 200
        assert resp.json()["memory"] == "Test memory"

        # Update
        resp = test_client.patch(
            f"/memories/{memory_id}",
            json={"memory": "Updated", "user_id": "alice", "topics": ["test"]},
        )
        assert resp.status_code == 200
        assert resp.json()["memory"] == "Updated"

        # Delete
        resp = test_client.delete(f"/memories/{memory_id}?user_id=alice")
        assert resp.status_code == 204

        # Verify deleted
        resp = test_client.get(f"/memories/{memory_id}?user_id=alice")
        assert resp.status_code == 404
