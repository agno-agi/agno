"""
Unit tests for MemoryManager / SessionSummaryManager identity (id/name).

These cover the behavior that lets two managers of the same type be
distinguished in the registry (addresses duplicate-id issue):
- Auto-generated unique id when not provided
- Explicit id/name passthrough
- Stable id within a single instance
"""

from agno.memory.manager import MemoryManager
from agno.session.summary import SessionSummaryManager

# =============================================================================
# MemoryManager identity
# =============================================================================


class TestMemoryManagerIdentity:
    """Tests for MemoryManager id/name."""

    def test_auto_generates_id(self):
        """Test that id is auto-generated when not provided."""
        mm = MemoryManager()

        assert mm.id is not None
        assert mm.id.startswith("memory_manager_")

    def test_auto_generated_ids_are_unique(self):
        """Test that two managers without explicit id get distinct ids."""
        mm1 = MemoryManager()
        mm2 = MemoryManager()

        assert mm1.id != mm2.id

    def test_explicit_id_passthrough(self):
        """Test that an explicitly provided id is used as-is."""
        mm = MemoryManager(id="my_memory")

        assert mm.id == "my_memory"

    def test_name_defaults_to_none(self):
        """Test that name defaults to None."""
        mm = MemoryManager()

        assert mm.name is None

    def test_explicit_name_passthrough(self):
        """Test that an explicitly provided name is used as-is."""
        mm = MemoryManager(id="my_memory", name="My Memory")

        assert mm.name == "My Memory"

    def test_id_is_stable_within_instance(self):
        """Test that the id does not change across attribute access."""
        mm = MemoryManager()

        assert mm.id == mm.id


# =============================================================================
# SessionSummaryManager identity
# =============================================================================


class TestSessionSummaryManagerIdentity:
    """Tests for SessionSummaryManager id/name."""

    def test_auto_generates_id(self):
        """Test that id is auto-generated when not provided."""
        sm = SessionSummaryManager()

        assert sm.id is not None
        assert sm.id.startswith("session_summary_manager_")

    def test_auto_generated_ids_are_unique(self):
        """Test that two managers without explicit id get distinct ids."""
        sm1 = SessionSummaryManager(last_n_runs=10)
        sm2 = SessionSummaryManager(conversation_limit=50)

        assert sm1.id != sm2.id

    def test_explicit_id_passthrough(self):
        """Test that an explicitly provided id is used as-is."""
        sm = SessionSummaryManager(id="concise_summary")

        assert sm.id == "concise_summary"

    def test_name_defaults_to_none(self):
        """Test that name defaults to None."""
        sm = SessionSummaryManager()

        assert sm.name is None

    def test_explicit_name_passthrough(self):
        """Test that an explicitly provided name is used as-is."""
        sm = SessionSummaryManager(id="concise_summary", name="Concise Summary")

        assert sm.name == "Concise Summary"

    def test_post_init_validation_still_runs(self):
        """Test that __post_init__ validation is preserved alongside id generation."""
        import pytest

        with pytest.raises(ValueError):
            SessionSummaryManager(last_n_runs=0)

        with pytest.raises(ValueError):
            SessionSummaryManager(conversation_limit=-1)
