"""Unit tests for MemoryManager.search_user_memories and related retrieval helpers.

Specifically covers:
- The retrieval / retrieval_limit defaults that were previously dead-code no-ops
  (lines ``retrieval_method = retrieval_method`` and ``limit = limit``).
- That MemoryManager accepts retrieval and retrieval_limit constructor parameters.
- That search_user_memories respects instance-level defaults when the caller
  does not supply explicit keyword arguments.
"""

from unittest.mock import MagicMock

import pytest

from agno.db.schemas import UserMemory
from agno.memory.manager import MemoryManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager_with_memories(memories: list[UserMemory], **kwargs) -> MemoryManager:
    """Return a MemoryManager whose db returns *memories* for any user_id."""
    db = MagicMock()
    db.get_user_memories = MagicMock(return_value=memories)
    return MemoryManager(db=db, **kwargs)


def _make_memories(n: int, user_id: str = "user1") -> list[UserMemory]:
    return [
        UserMemory(memory_id=f"mem{i}", user_id=user_id, memory=f"memory {i}", updated_at=i)
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# Tests: constructor parameters
# ---------------------------------------------------------------------------


class TestMemoryManagerConstructorDefaults:
    def test_default_retrieval_is_last_n(self):
        mm = MemoryManager()
        assert mm.retrieval == "last_n"

    def test_default_retrieval_limit_is_none(self):
        mm = MemoryManager()
        assert mm.retrieval_limit is None

    def test_custom_retrieval_accepted(self):
        mm = MemoryManager(retrieval="first_n")
        assert mm.retrieval == "first_n"

    def test_custom_retrieval_limit_accepted(self):
        mm = MemoryManager(retrieval_limit=5)
        assert mm.retrieval_limit == 5


# ---------------------------------------------------------------------------
# Tests: retrieval_limit default applied when limit is omitted
# ---------------------------------------------------------------------------


class TestRetrievalLimitDefault:
    def test_no_limit_returns_all_when_retrieval_limit_is_none(self):
        """With retrieval_limit=None (default), all memories should be returned."""
        memories = _make_memories(10)
        mm = _make_manager_with_memories(memories)
        result = mm.search_user_memories(user_id="user1")
        assert len(result) == 10

    def test_retrieval_limit_caps_results_when_limit_omitted(self):
        """If retrieval_limit=3 and caller omits limit, only 3 memories returned."""
        memories = _make_memories(10)
        mm = _make_manager_with_memories(memories, retrieval_limit=3)
        result = mm.search_user_memories(user_id="user1")
        assert len(result) == 3, (
            f"Expected retrieval_limit=3 to cap results at 3, got {len(result)}. "
            "The instance-level retrieval_limit was not applied (dead-code no-op regression)."
        )

    def test_explicit_limit_overrides_retrieval_limit(self):
        """An explicit limit= argument must override the instance retrieval_limit."""
        memories = _make_memories(10)
        mm = _make_manager_with_memories(memories, retrieval_limit=3)
        result = mm.search_user_memories(user_id="user1", limit=5)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Tests: retrieval default applied when retrieval_method is omitted
# ---------------------------------------------------------------------------


class TestRetrievalMethodDefault:
    def test_default_retrieval_last_n_returns_newest(self):
        """With retrieval='last_n', search should return the most recent memories."""
        memories = _make_memories(5)
        # updated_at values are 1..5; last_n with limit=2 should return memories 4 and 5
        mm = _make_manager_with_memories(memories, retrieval="last_n", retrieval_limit=2)
        result = mm.search_user_memories(user_id="user1")
        returned_ids = {m.memory_id for m in result}
        assert "mem5" in returned_ids and "mem4" in returned_ids

    def test_instance_retrieval_first_n_is_applied_when_method_omitted(self):
        """If retrieval='first_n', omitting retrieval_method should pick first_n."""
        memories = _make_memories(5)
        mm = _make_manager_with_memories(memories, retrieval="first_n", retrieval_limit=2)
        result = mm.search_user_memories(user_id="user1")
        returned_ids = {m.memory_id for m in result}
        assert "mem1" in returned_ids and "mem2" in returned_ids, (
            f"Expected first 2 memories (mem1, mem2) but got {returned_ids}. "
            "The instance-level retrieval default was not applied (dead-code no-op regression)."
        )

    def test_explicit_retrieval_method_overrides_instance_default(self):
        """An explicit retrieval_method= argument must override self.retrieval."""
        memories = _make_memories(5)
        # Instance default is first_n but caller explicitly requests last_n
        mm = _make_manager_with_memories(memories, retrieval="first_n", retrieval_limit=2)
        result = mm.search_user_memories(user_id="user1", retrieval_method="last_n")
        returned_ids = {m.memory_id for m in result}
        assert "mem5" in returned_ids and "mem4" in returned_ids
