"""Unit tests for SkillLoader abstract base class."""

from abc import ABC
from typing import List

import pytest

from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill


def test_skill_loader_is_abstract() -> None:
    """Test that SkillLoader is an abstract base class."""
    assert issubclass(SkillLoader, ABC)


def test_skill_loader_cannot_be_instantiated() -> None:
    """Test that SkillLoader cannot be instantiated directly."""
    with pytest.raises(TypeError) as exc_info:
        SkillLoader()  # type: ignore
    assert "abstract" in str(exc_info.value).lower()


def test_skill_loader_requires_load_method() -> None:
    """Test that subclasses must implement load method."""

    class IncompleteLoader(SkillLoader):
        pass

    with pytest.raises(TypeError) as exc_info:
        IncompleteLoader()  # type: ignore
    assert "abstract" in str(exc_info.value).lower()


def test_skill_loader_concrete_implementation() -> None:
    """Test that a complete implementation can be instantiated."""

    class ConcreteLoader(SkillLoader):
        def load(self) -> List[Skill]:
            return []

    loader = ConcreteLoader()
    assert isinstance(loader, SkillLoader)
    assert loader.load() == []


def test_skill_loader_load_returns_list() -> None:
    """Test that load method returns a list of Skills."""

    class TestLoader(SkillLoader):
        def load(self) -> List[Skill]:
            return [
                Skill(
                    name="test-skill",
                    description="Test",
                    instructions="Instructions",
                    source_path="/path",
                )
            ]

    loader = TestLoader()
    result = loader.load()

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], Skill)
    assert result[0].name == "test-skill"


def test_skill_loader_load_can_return_empty_list() -> None:
    """Test that load method can return an empty list."""

    class EmptyLoader(SkillLoader):
        def load(self) -> List[Skill]:
            return []

    loader = EmptyLoader()
    result = loader.load()

    assert result == []
    assert isinstance(result, list)


def test_skill_loader_load_can_return_multiple_skills() -> None:
    """Test that load method can return multiple skills."""

    class MultiSkillLoader(SkillLoader):
        def load(self) -> List[Skill]:
            return [
                Skill(
                    name="skill-1",
                    description="First skill",
                    instructions="Instructions 1",
                    source_path="/path/1",
                ),
                Skill(
                    name="skill-2",
                    description="Second skill",
                    instructions="Instructions 2",
                    source_path="/path/2",
                ),
            ]

    loader = MultiSkillLoader()
    result = loader.load()

    assert len(result) == 2
    assert result[0].name == "skill-1"
    assert result[1].name == "skill-2"
