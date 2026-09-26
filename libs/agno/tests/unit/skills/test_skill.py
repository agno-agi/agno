"""Unit tests for Skill dataclass."""

import json
from pathlib import Path

import pytest

from agno.skills.errors import SkillValidationError
from agno.skills.skill import Skill

# --- Skill Creation Tests ---


def test_skill_creation_with_all_fields(sample_skill: Skill) -> None:
    """Test creating a Skill with all fields populated."""
    assert sample_skill.name == "test-skill"
    assert sample_skill.description == "A test skill for unit testing"
    assert "Follow these instructions" in sample_skill.instructions
    assert sample_skill.source_path == "/path/to/test-skill"
    assert sample_skill.scripts == ["helper.py", "runner.sh"]
    assert sample_skill.references == ["guide.md", "api-docs.md"]
    assert sample_skill.metadata == {"version": "1.0.0", "author": "test-author", "tags": ["test", "example"]}
    assert sample_skill.license == "MIT"


def test_skill_creation_minimal(minimal_skill: Skill) -> None:
    """Test creating a Skill with only required fields."""
    assert minimal_skill.name == "minimal-skill"
    assert minimal_skill.description == "A minimal skill"
    assert minimal_skill.instructions == "Minimal instructions"
    assert minimal_skill.source_path == "/path/to/minimal-skill"
    # Optional fields should have default values
    assert minimal_skill.scripts == []
    assert minimal_skill.references == []
    assert minimal_skill.metadata is None
    assert minimal_skill.license is None


def test_skill_creation_with_empty_lists() -> None:
    """Test creating a Skill with explicitly empty lists."""
    skill = Skill(
        name="empty-lists",
        description="Skill with empty lists",
        instructions="Instructions",
        source_path="/path",
        scripts=[],
        references=[],
    )
    assert skill.scripts == []
    assert skill.references == []


def test_skill_source_type_defaults_to_local(minimal_skill: Skill) -> None:
    """Test that a path-backed Skill defaults to source_type 'local'."""
    assert minimal_skill.source_type == "local"


def test_skill_positional_construction_is_unchanged() -> None:
    """Test that the fields added for content-carrying skills shifted no existing argument slot."""
    skill = Skill(
        "positional",
        "Positional description",
        "Positional instructions",
        "/path",
        ["helper.py"],
        ["guide.md"],
        {"version": "1.0.0"},
        "MIT",
        "requires python>=3.9",
        ["get_skill_script"],
    )

    assert skill.source_path == "/path"
    assert skill.scripts == ["helper.py"]
    assert skill.references == ["guide.md"]
    assert skill.metadata == {"version": "1.0.0"}
    assert skill.license == "MIT"
    assert skill.compatibility == "requires python>=3.9"
    assert skill.allowed_tools == ["get_skill_script"]
    assert skill.source_type == "local"


def test_skill_accepts_a_path_source_path() -> None:
    """Test that source_path accepts a pathlib.Path, not only a str."""
    skill = Skill(
        name="path-skill",
        description="Path-backed via a pathlib.Path",
        instructions="Instructions",
        source_path=Path("/path/to/skill"),
    )

    assert skill.source_path == Path("/path/to/skill")


# --- Content-Carrying Skill Tests ---


def test_content_carrying_skill_creation(content_skill: Skill) -> None:
    """Test creating a Skill that carries its content instead of a source_path."""
    assert content_skill.source_path is None
    assert content_skill.source_type == "db"
    assert content_skill.scripts == ["hello.py", "sibling.py"]
    assert content_skill.references == ["guide.md"]
    assert content_skill.script_contents is not None
    assert "hello from content" in content_skill.script_contents["hello.py"]
    assert content_skill.reference_contents == {"guide.md": "# Guide\n\nThis is a reference guide."}


def test_content_carrying_skill_with_no_files() -> None:
    """Test that empty content dicts are a valid content-carrying skill."""
    skill = Skill(
        name="instructions-only",
        description="No scripts or references",
        instructions="Instructions",
        script_contents={},
        reference_contents={},
    )
    assert skill.source_path is None
    assert skill.scripts == []
    assert skill.references == []


def test_skill_rejects_both_path_and_contents() -> None:
    """Test that a Skill cannot be both path-backed and content-carrying."""
    with pytest.raises(SkillValidationError):
        Skill(
            name="both",
            description="Both shapes",
            instructions="Instructions",
            source_path="/path",
            reference_contents={"guide.md": "# Guide"},
        )


def test_skill_rejects_neither_path_nor_contents() -> None:
    """Test that a Skill must be either path-backed or content-carrying."""
    with pytest.raises(SkillValidationError):
        Skill(
            name="neither",
            description="Neither shape",
            instructions="Instructions",
        )


def test_skill_rejects_script_missing_content() -> None:
    """Test that a declared script with no matching content entry is rejected."""
    with pytest.raises(SkillValidationError) as exc_info:
        Skill(
            name="missing-script",
            description="Declares a script it has no content for",
            instructions="Instructions",
            scripts=["hello.py", "absent.py"],
            script_contents={"hello.py": "print('hi')"},
        )
    assert "absent.py" in str(exc_info.value)


def test_skill_rejects_reference_missing_content() -> None:
    """Test that a declared reference with no matching content entry is rejected."""
    with pytest.raises(SkillValidationError) as exc_info:
        Skill(
            name="missing-reference",
            description="Declares a reference it has no content for",
            instructions="Instructions",
            references=["guide.md"],
            script_contents={},
        )
    assert "guide.md" in str(exc_info.value)


# --- Skill Serialization Tests ---


def test_skill_to_dict(sample_skill: Skill) -> None:
    """Test converting Skill to dictionary."""
    skill_dict = sample_skill.to_dict()

    assert skill_dict["name"] == "test-skill"
    assert skill_dict["description"] == "A test skill for unit testing"
    assert "Follow these instructions" in skill_dict["instructions"]
    assert skill_dict["source_path"] == "/path/to/test-skill"
    assert skill_dict["scripts"] == ["helper.py", "runner.sh"]
    assert skill_dict["references"] == ["guide.md", "api-docs.md"]
    assert skill_dict["metadata"] == {"version": "1.0.0", "author": "test-author", "tags": ["test", "example"]}
    assert skill_dict["license"] == "MIT"


def test_skill_to_dict_minimal(minimal_skill: Skill) -> None:
    """Test converting minimal Skill to dictionary."""
    skill_dict = minimal_skill.to_dict()

    assert skill_dict["name"] == "minimal-skill"
    assert skill_dict["scripts"] == []
    assert skill_dict["references"] == []
    assert skill_dict["metadata"] is None
    assert skill_dict["license"] is None


def test_skill_from_dict(sample_skill_dict: dict) -> None:
    """Test creating Skill from dictionary."""
    skill = Skill.from_dict(sample_skill_dict)

    assert skill.name == "dict-skill"
    assert skill.description == "A skill from dictionary"
    assert skill.instructions == "Instructions from dict"
    assert skill.source_path == "/path/to/dict-skill"
    assert skill.scripts == ["script.py"]
    assert skill.references == ["ref.md"]
    assert skill.metadata == {"version": "2.0.0"}
    assert skill.license == "Apache-2.0"


def test_skill_from_dict_minimal() -> None:
    """Test creating Skill from minimal dictionary."""
    data = {
        "name": "minimal",
        "description": "Minimal description",
        "instructions": "Minimal instructions",
        "source_path": "/path",
    }
    skill = Skill.from_dict(data)

    assert skill.name == "minimal"
    assert skill.scripts == []
    assert skill.references == []
    assert skill.metadata is None
    assert skill.license is None


def test_skill_roundtrip(sample_skill: Skill) -> None:
    """Test that to_dict followed by from_dict preserves all data."""
    skill_dict = sample_skill.to_dict()
    recreated_skill = Skill.from_dict(skill_dict)

    assert recreated_skill.name == sample_skill.name
    assert recreated_skill.description == sample_skill.description
    assert recreated_skill.instructions == sample_skill.instructions
    assert recreated_skill.source_path == sample_skill.source_path
    assert recreated_skill.scripts == sample_skill.scripts
    assert recreated_skill.references == sample_skill.references
    assert recreated_skill.metadata == sample_skill.metadata
    assert recreated_skill.license == sample_skill.license


def test_content_skill_roundtrip(content_skill: Skill) -> None:
    """Test that to_dict followed by from_dict preserves a content-carrying skill."""
    recreated_skill = Skill.from_dict(content_skill.to_dict())

    assert recreated_skill == content_skill


def test_to_dict_serializes_a_path_source_path_to_str() -> None:
    """Test that a Path source_path is serialized as a str, keeping the dict JSON-encodable."""
    skill = Skill(
        name="path-skill",
        description="Path-backed via a pathlib.Path",
        instructions="Instructions",
        source_path=Path("/path/to/skill"),
    )

    skill_dict = skill.to_dict()

    assert isinstance(skill_dict["source_path"], str)
    assert skill_dict["source_path"] == str(Path("/path/to/skill"))
    # A raw Path is not JSON serializable, so without the coercion above this call raises.
    assert json.loads(json.dumps(skill_dict))["source_path"] == str(Path("/path/to/skill"))


def test_from_dict_restores_a_serialized_path_source_path() -> None:
    """Test that a skill built from a Path survives a JSON round trip, as a str path."""
    original = Skill(
        name="path-skill",
        description="Path-backed via a pathlib.Path",
        instructions="Instructions",
        source_path=Path("/path/to/skill"),
        scripts=[],
        references=[],
    )

    restored = Skill.from_dict(json.loads(json.dumps(original.to_dict())))

    # JSON has no path type, so the restored skill carries the equivalent str.
    assert restored.source_path == str(Path("/path/to/skill"))
    assert restored.name == original.name
    assert restored.instructions == original.instructions


# --- Skill Equality Tests ---


def test_skills_with_same_data_are_equal() -> None:
    """Test that two Skills with identical data are equal."""
    skill1 = Skill(
        name="equal-skill",
        description="Test description",
        instructions="Test instructions",
        source_path="/path",
    )
    skill2 = Skill(
        name="equal-skill",
        description="Test description",
        instructions="Test instructions",
        source_path="/path",
    )
    assert skill1 == skill2


def test_skills_with_different_names_are_not_equal() -> None:
    """Test that Skills with different names are not equal."""
    skill1 = Skill(
        name="skill-one",
        description="Same description",
        instructions="Same instructions",
        source_path="/path",
    )
    skill2 = Skill(
        name="skill-two",
        description="Same description",
        instructions="Same instructions",
        source_path="/path",
    )
    assert skill1 != skill2


def test_skills_with_different_optional_fields() -> None:
    """Test equality with different optional fields."""
    skill1 = Skill(
        name="same-name",
        description="Same",
        instructions="Same",
        source_path="/path",
        scripts=["script.py"],
    )
    skill2 = Skill(
        name="same-name",
        description="Same",
        instructions="Same",
        source_path="/path",
        scripts=["different.py"],
    )
    assert skill1 != skill2


# --- Error Handling Tests ---


def test_from_dict_missing_required_field() -> None:
    """Test that from_dict raises KeyError for missing required fields."""
    incomplete_data = {
        "name": "incomplete",
        "description": "Missing fields",
        # Missing: instructions
    }
    with pytest.raises(KeyError):
        Skill.from_dict(incomplete_data)
