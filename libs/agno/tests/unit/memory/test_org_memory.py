"""Unit tests for OrganizationMemory storage and MemoryCompiler functionality."""

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.db.schemas.org_memory import OrganizationMemory
from agno.memory_v2.memory_compiler import MemoryCompiler


class TestOrganizationMemorySchema:
    """Tests for the OrganizationMemory dataclass."""

    def test_create_org_memory(self):
        """Test basic OrganizationMemory creation."""
        org = OrganizationMemory(org_id="test_org")
        assert org.org_id == "test_org"
        assert org.memory_layers == {}
        assert org.created_at is not None
        assert org.updated_at is not None

    def test_org_memory_with_data(self):
        """Test OrganizationMemory with initial data."""
        org = OrganizationMemory(
            org_id="test_org",
            memory_layers={
                "context": {"domain": "AI", "product": "Agent Framework"},
                "policies": {"safety": "Never provide harmful content"},
            },
        )
        assert org.memory_layers["context"]["domain"] == "AI"
        assert "safety" in org.memory_layers["policies"]

    def test_org_memory_from_dict(self):
        """Test creating OrganizationMemory from dict."""
        data = {
            "org_id": "test_org",
            "memory_layers": {"context": {"domain": "Healthcare"}},
            "created_at": 1000,
            "updated_at": 2000,
        }
        org = OrganizationMemory.from_dict(data)
        assert org.org_id == "test_org"
        assert org.memory_layers["context"]["domain"] == "Healthcare"
        assert org.created_at == 1000
        assert org.updated_at == 2000


class TestMemoryCompilerOrgApplyMethods:
    """Tests for MemoryCompiler org layer manipulation methods."""

    def test_apply_save_to_context_layer(self):
        """Test saving to context layer."""
        compiler = MemoryCompiler()
        org = OrganizationMemory(org_id="test")

        result = compiler._apply_save_to_org_layer(org, "context", "domain", "AI")

        assert "Saved" in result
        assert org.memory_layers["context"]["domain"] == "AI"

    def test_apply_save_to_policies_layer(self):
        """Test saving to policies layer."""
        compiler = MemoryCompiler()
        org = OrganizationMemory(org_id="test")

        result = compiler._apply_save_to_org_layer(org, "policies", "safety_rule", "No PII")

        assert "Saved" in result
        assert org.memory_layers["policies"]["safety_rule"] == "No PII"

    def test_apply_save_to_unknown_layer_returns_error(self):
        """Test that unknown layer returns error."""
        compiler = MemoryCompiler()
        org = OrganizationMemory(org_id="test")

        result = compiler._apply_save_to_org_layer(org, "unknown", "key", "value")

        assert "Error" in result

    def test_apply_delete_from_context_layer(self):
        """Test deleting from context layer."""
        compiler = MemoryCompiler()
        org = OrganizationMemory(
            org_id="test",
            memory_layers={"context": {"domain": "AI", "product": "Agents"}},
        )

        result = compiler._apply_delete_from_org_layer(org, "context", "domain")

        assert "Forgot" in result
        assert "domain" not in org.memory_layers["context"]
        assert "product" in org.memory_layers["context"]

    def test_apply_delete_from_policies_layer(self):
        """Test deleting from policies layer."""
        compiler = MemoryCompiler()
        org = OrganizationMemory(
            org_id="test",
            memory_layers={"policies": {"safety": "Be safe", "tone": "Professional"}},
        )

        result = compiler._apply_delete_from_org_layer(org, "policies", "safety")

        assert "Forgot" in result
        assert "safety" not in org.memory_layers["policies"]
        assert "tone" in org.memory_layers["policies"]

    def test_apply_delete_nonexistent_key(self):
        """Test deleting non-existent key returns appropriate message."""
        compiler = MemoryCompiler()
        org = OrganizationMemory(org_id="test")

        result = compiler._apply_delete_from_org_layer(org, "context", "nonexistent")

        assert "not found" in result


class TestMemoryCompilerOrgCompile:
    """Tests for MemoryCompiler.compile_org_memory formatting."""

    def test_compile_empty_org_memory_returns_empty(self):
        """Test compiling non-existent org returns empty string."""
        db = InMemoryDb()
        compiler = MemoryCompiler(db=db)

        result = compiler.compile_org_memory("nonexistent_org")

        assert result == ""

    def test_compile_org_memory_formatting(self):
        """Test that compile produces expected XML format."""
        db = InMemoryDb()
        org = OrganizationMemory(
            org_id="test_org",
            memory_layers={
                "context": {"domain": "Healthcare"},
                "policies": {"compliance": "HIPAA required"},
            },
        )
        db.upsert_org_memory(org)
        compiler = MemoryCompiler(db=db)

        result = compiler.compile_org_memory("test_org")

        assert "<org_memory>" in result
        assert "</org_memory>" in result
        assert "Healthcare" in result
        assert "HIPAA" in result


class TestInMemoryDbOrgMemory:
    """Tests for InMemoryDb organization memory operations."""

    def test_upsert_and_get_org_memory(self):
        """Test basic roundtrip: upsert -> get."""
        db = InMemoryDb()
        org = OrganizationMemory(
            org_id="org1",
            memory_layers={"context": {"domain": "FinTech"}},
        )

        result = db.upsert_org_memory(org)

        assert isinstance(result, OrganizationMemory)
        assert result.org_id == "org1"

        fetched = db.get_org_memory("org1")
        assert fetched is not None
        assert fetched.org_id == "org1"
        assert fetched.memory_layers["context"]["domain"] == "FinTech"

    def test_get_nonexistent_org_returns_none(self):
        """Test getting non-existent org returns None."""
        db = InMemoryDb()

        result = db.get_org_memory("nonexistent")

        assert result is None

    def test_upsert_updates_existing_org(self):
        """Test that upsert updates existing org memory."""
        db = InMemoryDb()
        org1 = OrganizationMemory(
            org_id="org1",
            memory_layers={"context": {"domain": "Original"}},
        )
        db.upsert_org_memory(org1)

        org2 = OrganizationMemory(
            org_id="org1",
            memory_layers={"context": {"domain": "Updated", "product": "New"}},
        )
        db.upsert_org_memory(org2)

        fetched = db.get_org_memory("org1")
        assert fetched.memory_layers["context"]["domain"] == "Updated"
        assert fetched.memory_layers["context"]["product"] == "New"

    def test_delete_org_memory(self):
        """Test deleting an organization's memory."""
        db = InMemoryDb()
        org = OrganizationMemory(org_id="org1")
        db.upsert_org_memory(org)

        db.delete_org_memory("org1")

        fetched = db.get_org_memory("org1")
        assert fetched is None

    def test_delete_nonexistent_org_no_error(self):
        """Test deleting non-existent org doesn't raise error."""
        db = InMemoryDb()

        db.delete_org_memory("nonexistent")  # Should not raise


class TestMemoryCompilerOrgLayerOperations:
    """Tests for full save/delete with DB persistence."""

    def test_save_to_org_memory_layer_persists(self):
        """Test that _save_to_org_memory_layer persists to DB."""
        db = InMemoryDb()
        compiler = MemoryCompiler(db=db)

        result = compiler._save_to_org_memory_layer("org1", "context", "domain", "AI")

        assert "Saved" in result
        fetched = db.get_org_memory("org1")
        assert fetched is not None
        assert fetched.memory_layers["context"]["domain"] == "AI"

    def test_delete_from_org_memory_layer_persists(self):
        """Test that _delete_from_org_memory_layer persists to DB."""
        db = InMemoryDb()
        org = OrganizationMemory(
            org_id="org1",
            memory_layers={"context": {"domain": "AI", "product": "Agents"}},
        )
        db.upsert_org_memory(org)
        compiler = MemoryCompiler(db=db)

        result = compiler._delete_from_org_memory_layer("org1", "context", "domain")

        assert "Forgot" in result
        fetched = db.get_org_memory("org1")
        assert "domain" not in fetched.memory_layers["context"]
        assert "product" in fetched.memory_layers["context"]


class TestOrgMemoryMultiUserScenario:
    """Tests for organization memory shared across multiple users."""

    def test_multiple_users_same_org_memory(self):
        """Test that multiple users can access the same org memory."""
        db = InMemoryDb()
        compiler = MemoryCompiler(db=db)

        # Set up org memory
        compiler._save_to_org_memory_layer("shared_org", "context", "domain", "AI")
        compiler._save_to_org_memory_layer("shared_org", "policies", "style", "Professional")

        # Both users should see the same org context
        user1_context = compiler.compile_org_memory("shared_org")
        user2_context = compiler.compile_org_memory("shared_org")

        assert user1_context == user2_context
        assert "AI" in user1_context
        assert "Professional" in user2_context

    def test_org_memory_update_visible_to_all(self):
        """Test that org memory updates are visible to all users."""
        db = InMemoryDb()
        compiler = MemoryCompiler(db=db)

        # Initial state
        compiler._save_to_org_memory_layer("shared_org", "context", "domain", "AI")

        # First user reads
        context_before = compiler.compile_org_memory("shared_org")
        assert "AI" in context_before

        # Update org memory
        compiler._save_to_org_memory_layer("shared_org", "context", "domain", "Healthcare")

        # Both users see the update
        context_after = compiler.compile_org_memory("shared_org")
        assert "Healthcare" in context_after
        assert "AI" not in context_after
