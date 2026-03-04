"""Tests for conditional strict parameter in tool function building.

Verifies that learning stores, memory manager, and culture manager respect the
model's supports_native_structured_outputs flag when building tool functions,
rather than always hardcoding strict=True.

This prevents VertexAI Claude and AWS Claude from rejecting tool definitions
that include the 'strict' field (VertexAI returns:
"tools.0.custom.strict: Extra inputs are not permitted").

Covers all affected components:
- UserProfileStore
- UserMemoryStore
- SessionContextStore
- EntityMemoryStore
- LearnedKnowledgeStore
- MemoryManager
- CultureManager
"""

from unittest.mock import MagicMock

import pytest


def _dummy_tool(x: str) -> str:
    """A dummy tool for testing."""
    return x


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def model_with_strict():
    """Mock model that supports native structured outputs (e.g. OpenAI)."""
    model = MagicMock()
    model.supports_native_structured_outputs = True
    return model


@pytest.fixture
def model_without_strict():
    """Mock model that does NOT support native structured outputs (e.g. VertexAI Claude)."""
    model = MagicMock()
    model.supports_native_structured_outputs = False
    return model


# ---------------------------------------------------------------------------
# UserProfileStore
# ---------------------------------------------------------------------------


class TestUserProfileStoreStrict:
    def _make_store(self, model):
        from agno.learn.config import UserProfileConfig
        from agno.learn.stores.user_profile import UserProfileStore

        config = UserProfileConfig(model=model)
        return UserProfileStore(config=config)

    def test_strict_enabled_when_model_supports(self, model_with_strict):
        store = self._make_store(model_with_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert functions[0].strict is True

    def test_strict_disabled_when_model_does_not_support(self, model_without_strict):
        store = self._make_store(model_without_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict

    def test_strict_disabled_when_model_is_none(self):
        store = self._make_store(None)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict


# ---------------------------------------------------------------------------
# UserMemoryStore
# ---------------------------------------------------------------------------


class TestUserMemoryStoreStrict:
    def _make_store(self, model):
        from agno.learn.config import UserMemoryConfig
        from agno.learn.stores.user_memory import UserMemoryStore

        config = UserMemoryConfig(model=model)
        return UserMemoryStore(config=config)

    def test_strict_enabled_when_model_supports(self, model_with_strict):
        store = self._make_store(model_with_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert functions[0].strict is True

    def test_strict_disabled_when_model_does_not_support(self, model_without_strict):
        store = self._make_store(model_without_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict

    def test_strict_disabled_when_model_is_none(self):
        store = self._make_store(None)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict


# ---------------------------------------------------------------------------
# SessionContextStore
# ---------------------------------------------------------------------------


class TestSessionContextStoreStrict:
    def _make_store(self, model):
        from agno.learn.config import SessionContextConfig
        from agno.learn.stores.session_context import SessionContextStore

        config = SessionContextConfig(model=model)
        return SessionContextStore(config=config)

    def test_strict_enabled_when_model_supports(self, model_with_strict):
        store = self._make_store(model_with_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert functions[0].strict is True

    def test_strict_disabled_when_model_does_not_support(self, model_without_strict):
        store = self._make_store(model_without_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict

    def test_strict_disabled_when_model_is_none(self):
        store = self._make_store(None)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict


# ---------------------------------------------------------------------------
# EntityMemoryStore
# ---------------------------------------------------------------------------


class TestEntityMemoryStoreStrict:
    def _make_store(self, model):
        from agno.learn.config import EntityMemoryConfig
        from agno.learn.stores.entity_memory import EntityMemoryStore

        config = EntityMemoryConfig(model=model)
        return EntityMemoryStore(config=config)

    def test_strict_enabled_when_model_supports(self, model_with_strict):
        store = self._make_store(model_with_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert functions[0].strict is True

    def test_strict_disabled_when_model_does_not_support(self, model_without_strict):
        store = self._make_store(model_without_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict

    def test_strict_disabled_when_model_is_none(self):
        store = self._make_store(None)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict


# ---------------------------------------------------------------------------
# LearnedKnowledgeStore
# ---------------------------------------------------------------------------


class TestLearnedKnowledgeStoreStrict:
    def _make_store(self, model):
        from agno.learn.config import LearnedKnowledgeConfig
        from agno.learn.stores.learned_knowledge import LearnedKnowledgeStore

        config = LearnedKnowledgeConfig(model=model)
        return LearnedKnowledgeStore(config=config)

    def test_strict_enabled_when_model_supports(self, model_with_strict):
        store = self._make_store(model_with_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert functions[0].strict is True

    def test_strict_disabled_when_model_does_not_support(self, model_without_strict):
        store = self._make_store(model_without_strict)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict

    def test_strict_disabled_when_model_is_none(self):
        store = self._make_store(None)
        functions = store._build_functions_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------


class TestMemoryManagerStrict:
    def _make_manager(self, model):
        from agno.memory.manager import MemoryManager

        # MemoryManager.__init__ validates model type via get_model(),
        # so create with None and set model directly for testing.
        manager = MemoryManager()
        manager.model = model
        return manager

    def test_strict_enabled_when_model_supports(self, model_with_strict):
        manager = self._make_manager(model_with_strict)
        functions = manager.determine_tools_for_model([_dummy_tool])
        assert len(functions) == 1
        assert functions[0].strict is True

    def test_strict_disabled_when_model_does_not_support(self, model_without_strict):
        manager = self._make_manager(model_without_strict)
        functions = manager.determine_tools_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict

    def test_strict_disabled_when_model_is_none(self):
        manager = self._make_manager(None)
        functions = manager.determine_tools_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict


# ---------------------------------------------------------------------------
# CultureManager
# ---------------------------------------------------------------------------


class TestCultureManagerStrict:
    def _make_manager(self, model):
        from agno.culture.manager import CultureManager

        # CultureManager.__init__ validates model type via get_model(),
        # so create with None and set model directly for testing.
        manager = CultureManager()
        manager.model = model
        return manager

    def test_strict_enabled_when_model_supports(self, model_with_strict):
        manager = self._make_manager(model_with_strict)
        functions = manager._determine_tools_for_model([_dummy_tool])
        assert len(functions) == 1
        assert functions[0].strict is True

    def test_strict_disabled_when_model_does_not_support(self, model_without_strict):
        manager = self._make_manager(model_without_strict)
        functions = manager._determine_tools_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict

    def test_strict_disabled_when_model_is_none(self):
        manager = self._make_manager(None)
        functions = manager._determine_tools_for_model([_dummy_tool])
        assert len(functions) == 1
        assert not functions[0].strict


# ---------------------------------------------------------------------------
# Cross-cutting: tool_definition output
# ---------------------------------------------------------------------------


class TestToolDefinitionOutput:
    """Verify that the strict flag propagates to the serialized tool definition."""

    def test_tool_definition_includes_strict_when_supported(self, model_with_strict):
        from agno.learn.config import UserProfileConfig
        from agno.learn.stores.user_profile import UserProfileStore

        config = UserProfileConfig(model=model_with_strict)
        store = UserProfileStore(config=config)
        functions = store._build_functions_for_model([_dummy_tool])
        tool_def = functions[0].to_dict()
        assert tool_def.get("strict") is True

    def test_tool_definition_omits_strict_when_not_supported(self, model_without_strict):
        from agno.learn.config import UserProfileConfig
        from agno.learn.stores.user_profile import UserProfileStore

        config = UserProfileConfig(model=model_without_strict)
        store = UserProfileStore(config=config)
        functions = store._build_functions_for_model([_dummy_tool])
        tool_def = functions[0].to_dict()
        # strict should either be absent or False
        assert tool_def.get("strict") is not True
