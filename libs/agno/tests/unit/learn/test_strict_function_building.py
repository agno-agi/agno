from types import SimpleNamespace
from typing import Optional

import pytest

from agno.learn.config import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.learn.stores.entity_memory import EntityMemoryStore
from agno.learn.stores.learned_knowledge import LearnedKnowledgeStore
from agno.learn.stores.session_context import SessionContextStore
from agno.learn.stores.user_memory import UserMemoryStore
from agno.learn.stores.user_profile import UserProfileStore


def sample_learning_tool(required_value: str, optional_value: Optional[str] = None) -> str:
    """Sample learning tool."""
    return required_value if optional_value is None else optional_value


@pytest.mark.parametrize(
    ("store_cls", "config_cls"),
    [
        (UserProfileStore, UserProfileConfig),
        (UserMemoryStore, UserMemoryConfig),
        (SessionContextStore, SessionContextConfig),
        (LearnedKnowledgeStore, LearnedKnowledgeConfig),
        (EntityMemoryStore, EntityMemoryConfig),
    ],
)
def test_learning_store_functions_omit_strict_for_models_without_native_structured_outputs(store_cls, config_cls):
    model = SimpleNamespace(supports_native_structured_outputs=False)
    store = store_cls(config=config_cls(model=model))

    functions = store._build_functions_for_model([sample_learning_tool])

    assert len(functions) == 1
    assert functions[0].strict is None
    assert "strict" not in functions[0].to_dict()
    assert "required_value" in functions[0].parameters["required"]
    assert "optional_value" not in functions[0].parameters["required"]


@pytest.mark.parametrize(
    ("store_cls", "config_cls"),
    [
        (UserProfileStore, UserProfileConfig),
        (UserMemoryStore, UserMemoryConfig),
        (SessionContextStore, SessionContextConfig),
        (LearnedKnowledgeStore, LearnedKnowledgeConfig),
        (EntityMemoryStore, EntityMemoryConfig),
    ],
)
def test_learning_store_functions_keep_strict_for_native_structured_output_models(store_cls, config_cls):
    model = SimpleNamespace(supports_native_structured_outputs=True)
    store = store_cls(config=config_cls(model=model))

    functions = store._build_functions_for_model([sample_learning_tool])

    assert len(functions) == 1
    assert functions[0].strict is True
    assert functions[0].to_dict()["strict"] is True
    assert "required_value" in functions[0].parameters["required"]
    assert "optional_value" in functions[0].parameters["required"]
