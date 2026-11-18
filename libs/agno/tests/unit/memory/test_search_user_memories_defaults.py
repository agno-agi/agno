"""Tests for what MemoryManager.search_user_memories does with no arguments.

The docstring used to promise defaults pulled from self.retrieval_limit and
self.retrieval, neither of which exists on the class, and the two lines meant
to apply them assigned the parameters to themselves. These pin down what the
method actually does so the docstring and the code cannot drift apart again.
"""

from unittest.mock import MagicMock

import pytest

from agno.db.schemas import UserMemory
from agno.memory.manager import MemoryManager


@pytest.fixture
def mock_db():
    """Create a mock synchronous database."""
    db = MagicMock()
    db.get_user_memories = MagicMock(return_value=[])
    return db


@pytest.fixture
def manager(mock_db):
    """Create a MemoryManager with mock db."""
    return MemoryManager(db=mock_db)


@pytest.fixture
def user_memories():
    """Four memories for one user, oldest to newest by updated_at."""
    return [
        UserMemory(memory_id="mem1", user_id="user1", memory="I like cats", updated_at=100),
        UserMemory(memory_id="mem2", user_id="user1", memory="I work at Acme", updated_at=200),
        UserMemory(memory_id="mem3", user_id="user1", memory="I prefer dark mode", updated_at=300),
        UserMemory(memory_id="mem4", user_id="user1", memory="I live in Berlin", updated_at=400),
    ]


class TestSearchUserMemoriesDefaults:
    def test_no_retrieval_method_behaves_as_last_n(self, manager, mock_db, user_memories):
        """An unset retrieval_method gives the same result as last_n."""
        mock_db.get_user_memories.return_value = user_memories

        implicit = manager.search_user_memories(user_id="user1")
        explicit = manager.search_user_memories(user_id="user1", retrieval_method="last_n")

        assert [m.memory_id for m in implicit] == [m.memory_id for m in explicit]

    def test_no_limit_returns_every_memory(self, manager, mock_db, user_memories):
        """An unset limit does not truncate."""
        mock_db.get_user_memories.return_value = user_memories

        result = manager.search_user_memories(user_id="user1")

        assert len(result) == len(user_memories)

    def test_limit_still_truncates(self, manager, mock_db, user_memories):
        """A limit that is passed is honoured, so the default is not a no-op path."""
        mock_db.get_user_memories.return_value = user_memories

        result = manager.search_user_memories(user_id="user1", limit=2)

        assert len(result) == 2

    def test_manager_has_no_retrieval_attributes(self):
        """The attributes the docstring used to name are not on the class."""
        mm = MemoryManager()

        assert not hasattr(mm, "retrieval")
        assert not hasattr(mm, "retrieval_limit")
