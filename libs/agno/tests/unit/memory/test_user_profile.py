"""Unit tests for UserProfile storage and MemoryCompiler functionality."""

import pytest

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.db.schemas.user_profile import UserProfile
from agno.memory_v2.memory_compiler import MemoryCompiler


class TestUserProfileSchema:
    """Tests for the UserProfile dataclass."""

    def test_create_user_profile(self):
        """Test basic UserProfile creation."""
        profile = UserProfile(user_id="test_user")
        assert profile.user_id == "test_user"
        assert profile.user_profile == {}
        assert profile.memory_layers == {}
        assert profile.created_at is not None
        assert profile.updated_at is not None

    def test_user_profile_with_data(self):
        """Test UserProfile with initial data."""
        profile = UserProfile(
            user_id="test_user",
            user_profile={"name": "John", "role": "Engineer"},
            memory_layers={
                "policies": {"response_style": "concise"},
                "knowledge": [{"key": "lang", "value": "Python"}],
            },
        )
        assert profile.user_profile["name"] == "John"
        assert profile.policies == {"response_style": "concise"}
        assert len(profile.knowledge) == 1

    def test_user_profile_to_dict_and_from_dict(self):
        """Test serialization roundtrip."""
        profile = UserProfile(
            user_id="test_user",
            user_profile={"name": "Jane"},
            memory_layers={"feedback": {"positive": ["good"]}},
        )
        data = profile.to_dict()
        restored = UserProfile.from_dict(data)
        assert restored.user_id == profile.user_id
        assert restored.user_profile == profile.user_profile
        assert restored.memory_layers == profile.memory_layers

    def test_user_id_required(self):
        """Test that user_id is required and cannot be empty."""
        with pytest.raises(ValueError):
            UserProfile(user_id="")


class TestMemoryCompilerApplyMethods:
    """Tests for MemoryCompiler layer manipulation methods."""

    def test_apply_save_to_profile_layer(self):
        """Test saving to profile layer."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        result = compiler._apply_save_to_layer(profile, "profile", "name", "John Doe")

        assert "Saved" in result
        assert profile.user_profile["name"] == "John Doe"

    def test_apply_save_to_policy_layer(self):
        """Test saving to policy layer."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        result = compiler._apply_save_to_layer(profile, "policy", "response_style", "concise")

        assert "Saved" in result
        assert profile.memory_layers["policies"]["response_style"] == "concise"

    def test_apply_save_to_knowledge_layer(self):
        """Test saving to knowledge layer."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        result = compiler._apply_save_to_layer(profile, "knowledge", "interests", "hiking")

        assert "Saved" in result
        assert len(profile.memory_layers["knowledge"]) == 1
        assert profile.memory_layers["knowledge"][0]["key"] == "interests"
        assert profile.memory_layers["knowledge"][0]["value"] == "hiking"

    def test_apply_save_to_knowledge_updates_existing(self):
        """Test that saving to knowledge with same key updates existing entry."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        compiler._apply_save_to_layer(profile, "knowledge", "interests", "hiking")
        compiler._apply_save_to_layer(profile, "knowledge", "interests", "climbing")

        assert len(profile.memory_layers["knowledge"]) == 1
        assert profile.memory_layers["knowledge"][0]["value"] == "climbing"

    def test_apply_save_to_feedback_positive(self):
        """Test saving positive feedback."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        result = compiler._apply_save_to_layer(profile, "feedback", "positive", "liked bullet points")

        assert "Saved" in result
        assert "liked bullet points" in profile.memory_layers["feedback"]["positive"]

    def test_apply_save_to_feedback_negative(self):
        """Test saving negative feedback."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        result = compiler._apply_save_to_layer(profile, "feedback", "negative", "too verbose")

        assert "Saved" in result
        assert "too verbose" in profile.memory_layers["feedback"]["negative"]

    def test_apply_save_to_feedback_invalid_key(self):
        """Test that feedback with invalid key returns error."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        result = compiler._apply_save_to_layer(profile, "feedback", "invalid", "value")

        assert "Error" in result

    def test_apply_save_to_unknown_layer_returns_error(self):
        """Test that unknown info_type returns error."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        result = compiler._apply_save_to_layer(profile, "unknown", "key", "value")

        assert "Error" in result

    def test_apply_delete_from_profile_layer(self):
        """Test deleting from profile layer."""
        compiler = MemoryCompiler()
        profile = UserProfile(
            user_id="test",
            user_profile={"name": "John", "role": "Engineer"},
        )

        result = compiler._apply_delete_from_layer(profile, "profile", "name")

        assert "Forgot" in result
        assert "name" not in profile.user_profile
        assert "role" in profile.user_profile

    def test_apply_delete_from_policy_layer(self):
        """Test deleting from policy layer."""
        compiler = MemoryCompiler()
        profile = UserProfile(
            user_id="test",
            memory_layers={"policies": {"style": "concise", "format": "markdown"}},
        )

        result = compiler._apply_delete_from_layer(profile, "policy", "style")

        assert "Forgot" in result
        assert "style" not in profile.memory_layers["policies"]
        assert "format" in profile.memory_layers["policies"]

    def test_apply_delete_from_knowledge_layer(self):
        """Test deleting from knowledge layer."""
        compiler = MemoryCompiler()
        profile = UserProfile(
            user_id="test",
            memory_layers={"knowledge": [{"key": "hobby", "value": "hiking"}, {"key": "lang", "value": "Python"}]},
        )

        result = compiler._apply_delete_from_layer(profile, "knowledge", "hobby")

        assert "Forgot" in result
        assert len(profile.memory_layers["knowledge"]) == 1
        assert profile.memory_layers["knowledge"][0]["key"] == "lang"

    def test_apply_delete_from_feedback_layer(self):
        """Test deleting from feedback layer clears the list."""
        compiler = MemoryCompiler()
        profile = UserProfile(
            user_id="test",
            memory_layers={"feedback": {"positive": ["good job"], "negative": ["too long"]}},
        )

        result = compiler._apply_delete_from_layer(profile, "feedback", "positive")

        assert "Forgot" in result
        assert profile.memory_layers["feedback"]["positive"] == []
        assert profile.memory_layers["feedback"]["negative"] == ["too long"]

    def test_apply_delete_nonexistent_key(self):
        """Test deleting non-existent key returns appropriate message."""
        compiler = MemoryCompiler()
        profile = UserProfile(user_id="test")

        result = compiler._apply_delete_from_layer(profile, "profile", "nonexistent")

        assert "not found" in result


class TestMemoryCompilerCompile:
    """Tests for MemoryCompiler.compile_user_profile formatting."""

    def test_compile_empty_profile(self):
        """Test compiling empty profile returns empty string."""
        db = InMemoryDb()
        compiler = MemoryCompiler(db=db)

        result = compiler.compile_user_profile("nonexistent_user")

        assert result == ""

    def test_compile_user_profile_formatting(self):
        """Test that compile produces expected XML format with compact JSON."""
        db = InMemoryDb()
        profile = UserProfile(
            user_id="test_user",
            user_profile={"name": "Jane"},
            memory_layers={"policies": {"style": "concise"}},
        )
        db.upsert_user_profile(profile)
        compiler = MemoryCompiler(db=db)

        result = compiler.compile_user_profile("test_user")

        assert "<user_memory>" in result
        assert "</user_memory>" in result
        assert '"profile":' in result
        assert '"policies":' in result
        # Verify compact JSON (no indent=2 spaces)
        assert "  " not in result or result.count("  ") == 0


class TestInMemoryDbUserProfile:
    """Tests for InMemoryDb user profile operations."""

    def test_upsert_and_get_user_profile(self):
        """Test basic roundtrip: upsert -> get."""
        db = InMemoryDb()
        profile = UserProfile(
            user_id="user1",
            user_profile={"name": "Test User"},
            memory_layers={"policies": {"verbose": "no"}},
        )

        result = db.upsert_user_profile(profile)

        assert isinstance(result, UserProfile)
        assert result.user_id == "user1"

        fetched = db.get_user_profile("user1")
        assert fetched is not None
        assert fetched.user_id == "user1"
        assert fetched.user_profile["name"] == "Test User"

    def test_get_nonexistent_profile_returns_none(self):
        """Test getting non-existent profile returns None."""
        db = InMemoryDb()

        result = db.get_user_profile("nonexistent")

        assert result is None

    def test_upsert_updates_existing_profile(self):
        """Test that upsert updates existing profile."""
        db = InMemoryDb()
        profile1 = UserProfile(user_id="user1", user_profile={"name": "Original"})
        db.upsert_user_profile(profile1)

        profile2 = UserProfile(user_id="user1", user_profile={"name": "Updated", "role": "Engineer"})
        db.upsert_user_profile(profile2)

        fetched = db.get_user_profile("user1")
        assert fetched.user_profile["name"] == "Updated"
        assert fetched.user_profile["role"] == "Engineer"

    def test_delete_user_profile(self):
        """Test deleting a user profile."""
        db = InMemoryDb()
        profile = UserProfile(user_id="user1")
        db.upsert_user_profile(profile)

        db.delete_user_profile("user1")

        fetched = db.get_user_profile("user1")
        assert fetched is None

    def test_delete_nonexistent_profile_no_error(self):
        """Test deleting non-existent profile doesn't raise error."""
        db = InMemoryDb()

        db.delete_user_profile("nonexistent")  # Should not raise

    def test_get_user_profile_deserialize_false(self):
        """Test getting profile as dict when deserialize=False."""
        db = InMemoryDb()
        profile = UserProfile(user_id="user1", user_profile={"name": "Test"})
        db.upsert_user_profile(profile)

        result = db.get_user_profile("user1", deserialize=False)

        assert isinstance(result, dict)
        assert result["user_id"] == "user1"
