"""Unit tests for skill validation logic."""

from pathlib import Path

import pytest

from agno.skills.validator import (
    ALLOWED_FIELDS,
    MAX_COMPATIBILITY_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_SKILL_NAME_LENGTH,
    _validate_allowed_tools,
    _validate_compatibility,
    _validate_description,
    _validate_license,
    _validate_metadata_fields,
    _validate_metadata_value,
    _validate_name,
    validate_metadata,
    validate_skill_directory,
)

# --- Name Validation Tests ---


def test_validate_name_valid() -> None:
    """Test that valid names pass validation."""
    errors = _validate_name("valid-skill-name")
    assert len(errors) == 0


def test_validate_name_with_numbers() -> None:
    """Test that names with numbers are valid."""
    errors = _validate_name("skill-v2")
    assert len(errors) == 0


def test_validate_name_single_word() -> None:
    """Test that single-word names are valid."""
    errors = _validate_name("skill")
    assert len(errors) == 0


def test_validate_name_too_long() -> None:
    """Test that names exceeding max length are rejected."""
    long_name = "a" * (MAX_SKILL_NAME_LENGTH + 1)
    errors = _validate_name(long_name)
    assert len(errors) > 0
    assert any("exceeds" in e.lower() or "character limit" in e.lower() for e in errors)


def test_validate_name_at_max_length() -> None:
    """Test that names at exactly max length are valid."""
    max_name = "a" * MAX_SKILL_NAME_LENGTH
    errors = _validate_name(max_name)
    assert not any("exceeds" in e.lower() for e in errors)


def test_validate_name_uppercase_rejected() -> None:
    """Test that uppercase names are rejected."""
    errors = _validate_name("Invalid-Name")
    assert len(errors) > 0
    assert any("lowercase" in e.lower() for e in errors)


def test_validate_name_with_underscore_rejected() -> None:
    """Test that names with underscores are rejected."""
    errors = _validate_name("invalid_name")
    assert len(errors) > 0
    assert any("invalid characters" in e.lower() for e in errors)


def test_validate_name_with_space_rejected() -> None:
    """Test that names with spaces are rejected."""
    errors = _validate_name("invalid name")
    assert len(errors) > 0
    assert any("invalid characters" in e.lower() for e in errors)


def test_validate_name_starting_with_hyphen_rejected() -> None:
    """Test that names starting with hyphen are rejected."""
    errors = _validate_name("-invalid")
    assert len(errors) > 0
    assert any("cannot start" in e.lower() or "start or end" in e.lower() for e in errors)


def test_validate_name_ending_with_hyphen_rejected() -> None:
    """Test that names ending with hyphen are rejected."""
    errors = _validate_name("invalid-")
    assert len(errors) > 0
    assert any("start or end" in e.lower() for e in errors)


def test_validate_name_consecutive_hyphens_rejected() -> None:
    """Test that names with consecutive hyphens are rejected."""
    errors = _validate_name("invalid--name")
    assert len(errors) > 0
    assert any("consecutive" in e.lower() for e in errors)


def test_validate_name_empty_rejected() -> None:
    """Test that empty names are rejected."""
    errors = _validate_name("")
    assert len(errors) > 0
    assert any("non-empty" in e.lower() for e in errors)


def test_validate_name_whitespace_only_rejected() -> None:
    """Test that whitespace-only names are rejected."""
    errors = _validate_name("   ")
    assert len(errors) > 0


def test_validate_name_directory_mismatch(tmp_path: Path) -> None:
    """Test that name must match directory name."""
    skill_dir = tmp_path / "actual-dir-name"
    skill_dir.mkdir()
    errors = _validate_name("different-name", skill_dir)
    assert len(errors) > 0
    assert any("must match" in e.lower() for e in errors)


def test_validate_name_directory_match(tmp_path: Path) -> None:
    """Test that matching name and directory passes."""
    skill_dir = tmp_path / "matching-name"
    skill_dir.mkdir()
    errors = _validate_name("matching-name", skill_dir)
    assert not any("must match" in e.lower() for e in errors)


@pytest.mark.parametrize(
    "invalid_name,expected_error",
    [
        ("UPPERCASE", "lowercase"),
        ("-leading-hyphen", "start or end"),
        ("trailing-hyphen-", "start or end"),
        ("double--hyphen", "consecutive"),
        ("has_underscore", "invalid characters"),
        ("has space", "invalid characters"),
        ("has.dot", "invalid characters"),
    ],
)
def test_validate_name_invalid_parametrized(invalid_name: str, expected_error: str) -> None:
    """Test various invalid name formats."""
    errors = _validate_name(invalid_name)
    assert len(errors) > 0
    assert any(expected_error.lower() in e.lower() for e in errors)


# --- Description Validation Tests ---


def test_validate_description_valid() -> None:
    """Test that valid descriptions pass validation."""
    errors = _validate_description("A valid skill description")
    assert len(errors) == 0


def test_validate_description_empty_rejected() -> None:
    """Test that empty descriptions are rejected."""
    errors = _validate_description("")
    assert len(errors) > 0
    assert any("non-empty" in e.lower() for e in errors)


def test_validate_description_whitespace_only_rejected() -> None:
    """Test that whitespace-only descriptions are rejected."""
    errors = _validate_description("   ")
    assert len(errors) > 0


def test_validate_description_too_long() -> None:
    """Test that descriptions exceeding max length are rejected."""
    long_desc = "a" * (MAX_DESCRIPTION_LENGTH + 1)
    errors = _validate_description(long_desc)
    assert len(errors) > 0
    assert any("exceeds" in e.lower() or "character limit" in e.lower() for e in errors)


def test_validate_description_at_max_length() -> None:
    """Test that descriptions at exactly max length are valid."""
    max_desc = "a" * MAX_DESCRIPTION_LENGTH
    errors = _validate_description(max_desc)
    assert len(errors) == 0


# --- Compatibility Validation Tests ---


def test_validate_compatibility_valid() -> None:
    """Test that valid compatibility strings pass validation."""
    errors = _validate_compatibility("Requires Python 3.8+")
    assert len(errors) == 0


def test_validate_compatibility_too_long() -> None:
    """Test that compatibility strings exceeding max length are rejected."""
    long_compat = "a" * (MAX_COMPATIBILITY_LENGTH + 1)
    errors = _validate_compatibility(long_compat)
    assert len(errors) > 0
    assert any("exceeds" in e.lower() for e in errors)


def test_validate_compatibility_at_max_length() -> None:
    """Test that compatibility at exactly max length is valid."""
    max_compat = "a" * MAX_COMPATIBILITY_LENGTH
    errors = _validate_compatibility(max_compat)
    assert len(errors) == 0


# --- Metadata Fields Validation Tests ---


def test_validate_metadata_fields_all_allowed() -> None:
    """Test that all allowed fields pass validation."""
    metadata = {field: "value" for field in ALLOWED_FIELDS}
    errors = _validate_metadata_fields(metadata)
    assert len(errors) == 0


def test_validate_metadata_fields_subset() -> None:
    """Test that subset of allowed fields passes."""
    metadata = {"name": "test", "description": "Test description"}
    errors = _validate_metadata_fields(metadata)
    assert len(errors) == 0


def test_validate_metadata_fields_unknown_rejected() -> None:
    """Test that unknown fields are rejected."""
    metadata = {"name": "test", "unknown_field": "value"}
    errors = _validate_metadata_fields(metadata)
    assert len(errors) > 0
    assert any("unexpected" in e.lower() and "unknown_field" in e.lower() for e in errors)


def test_validate_metadata_fields_multiple_unknown() -> None:
    """Test that multiple unknown fields are all reported."""
    metadata = {"name": "test", "bad1": "value", "bad2": "value"}
    errors = _validate_metadata_fields(metadata)
    assert len(errors) > 0
    assert any("bad1" in e for e in errors) or any("bad2" in e for e in errors)


def test_validate_metadata_fields_empty() -> None:
    """Test that empty metadata passes field validation."""
    errors = _validate_metadata_fields({})
    assert len(errors) == 0


# --- Complete Metadata Validation Tests ---


def test_validate_metadata_valid(tmp_path: Path) -> None:
    """Test that valid complete metadata passes."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    metadata = {
        "name": "test-skill",
        "description": "A valid test skill",
        "license": "MIT",
    }
    errors = validate_metadata(metadata, skill_dir)
    assert len(errors) == 0


def test_validate_metadata_missing_name() -> None:
    """Test that missing name is rejected."""
    metadata = {"description": "Missing name field"}
    errors = validate_metadata(metadata)
    assert len(errors) > 0
    assert any("name" in e.lower() and "missing" in e.lower() for e in errors)


def test_validate_metadata_missing_description() -> None:
    """Test that missing description is rejected."""
    metadata = {"name": "test-skill"}
    errors = validate_metadata(metadata)
    assert len(errors) > 0
    assert any("description" in e.lower() and "missing" in e.lower() for e in errors)


def test_validate_metadata_missing_both_required() -> None:
    """Test that missing both required fields generates multiple errors."""
    metadata = {"license": "MIT"}
    errors = validate_metadata(metadata)
    assert len(errors) >= 2


def test_validate_metadata_invalid_name_format() -> None:
    """Test that invalid name format is rejected."""
    metadata = {"name": "Invalid_Name", "description": "Valid description"}
    errors = validate_metadata(metadata)
    assert len(errors) > 0


def test_validate_metadata_with_optional_compatibility() -> None:
    """Test validation with optional compatibility field."""
    metadata = {
        "name": "test-skill",
        "description": "Valid description",
        "compatibility": "Requires Python 3.8+",
    }
    errors = validate_metadata(metadata)
    assert len(errors) == 0


def test_validate_metadata_with_invalid_compatibility() -> None:
    """Test validation with too-long compatibility field."""
    metadata = {
        "name": "test-skill",
        "description": "Valid description",
        "compatibility": "x" * (MAX_COMPATIBILITY_LENGTH + 1),
    }
    errors = validate_metadata(metadata)
    assert len(errors) > 0


# --- Skill Directory Validation Tests ---


def test_validate_skill_directory_valid(temp_skill_dir: Path) -> None:
    """Test that a valid skill directory passes validation."""
    errors = validate_skill_directory(temp_skill_dir)
    assert len(errors) == 0


def test_validate_skill_directory_not_exists(tmp_path: Path) -> None:
    """Test that non-existent directory is rejected."""
    nonexistent = tmp_path / "does-not-exist"
    errors = validate_skill_directory(nonexistent)
    assert len(errors) > 0
    assert any("does not exist" in e.lower() for e in errors)


def test_validate_skill_directory_is_file(tmp_path: Path) -> None:
    """Test that file path (not directory) is rejected."""
    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("content")
    errors = validate_skill_directory(file_path)
    assert len(errors) > 0
    assert any("not a directory" in e.lower() for e in errors)


def test_validate_skill_directory_missing_skill_md(tmp_path: Path) -> None:
    """Test that directory without SKILL.md is rejected."""
    skill_dir = tmp_path / "no-skill-md"
    skill_dir.mkdir()
    errors = validate_skill_directory(skill_dir)
    assert len(errors) > 0
    assert any("skill.md" in e.lower() for e in errors)


def test_validate_skill_directory_missing_frontmatter_start(skill_dir_missing_frontmatter: Path) -> None:
    """Test that SKILL.md without opening --- is rejected."""
    errors = validate_skill_directory(skill_dir_missing_frontmatter)
    assert len(errors) > 0
    assert any("frontmatter" in e.lower() and "---" in e for e in errors)


def test_validate_skill_directory_unclosed_frontmatter(tmp_path: Path) -> None:
    """Test that SKILL.md with unclosed frontmatter is rejected."""
    skill_dir = tmp_path / "unclosed"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: test
description: Test
# Missing closing ---
"""
    )
    errors = validate_skill_directory(skill_dir)
    assert len(errors) > 0
    assert any("closed" in e.lower() or "---" in e for e in errors)


def test_validate_skill_directory_invalid_yaml(tmp_path: Path) -> None:
    """Test that invalid YAML in frontmatter is rejected."""
    skill_dir = tmp_path / "bad-yaml"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: test
description: [unclosed bracket
---
# Instructions
"""
    )
    errors = validate_skill_directory(skill_dir)
    assert len(errors) > 0
    assert any("yaml" in e.lower() for e in errors)


def test_validate_skill_directory_invalid(invalid_skill_dir: Path) -> None:
    """Test that invalid skill directory fails validation."""
    errors = validate_skill_directory(invalid_skill_dir)
    assert len(errors) > 0


# --- Validator Constants Tests ---


def test_max_skill_name_length() -> None:
    """Test MAX_SKILL_NAME_LENGTH is set correctly."""
    assert MAX_SKILL_NAME_LENGTH == 64


def test_max_description_length() -> None:
    """Test MAX_DESCRIPTION_LENGTH is set correctly."""
    assert MAX_DESCRIPTION_LENGTH == 1024


def test_max_compatibility_length() -> None:
    """Test MAX_COMPATIBILITY_LENGTH is set correctly."""
    assert MAX_COMPATIBILITY_LENGTH == 500


def test_allowed_fields() -> None:
    """Test ALLOWED_FIELDS contains expected fields."""
    expected = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
    assert ALLOWED_FIELDS == expected


# --- License Validation Tests ---


def test_validate_license_valid() -> None:
    """Test that valid licenses pass validation."""
    errors = _validate_license("MIT")
    assert len(errors) == 0


def test_validate_license_apache() -> None:
    """Test that Apache-2.0 license is valid."""
    errors = _validate_license("Apache-2.0")
    assert len(errors) == 0


def test_validate_license_any_string() -> None:
    """Test that any string license is valid."""
    errors = _validate_license("CustomLicense")
    assert len(errors) == 0


def test_validate_license_wrong_type() -> None:
    """Test that non-string license is rejected."""
    errors = _validate_license(123)  # type: ignore
    assert len(errors) > 0
    assert "must be a string" in errors[0].lower()


# --- Allowed-Tools Validation Tests ---


def test_validate_allowed_tools_valid() -> None:
    """Test that valid allowed-tools list passes validation."""
    errors = _validate_allowed_tools(["tool1", "tool2"])
    assert len(errors) == 0


def test_validate_allowed_tools_empty_list() -> None:
    """Test that empty list is valid."""
    errors = _validate_allowed_tools([])
    assert len(errors) == 0


def test_validate_allowed_tools_not_list() -> None:
    """Test that non-list is rejected."""
    errors = _validate_allowed_tools("tool1")
    assert len(errors) > 0
    assert "must be a list" in errors[0].lower()


def test_validate_allowed_tools_not_strings() -> None:
    """Test that list with non-strings is rejected."""
    errors = _validate_allowed_tools(["tool1", 123])
    assert len(errors) > 0
    assert "list of strings" in errors[0].lower()


# --- Metadata Value Validation Tests ---


def test_validate_metadata_value_valid() -> None:
    """Test that valid dict passes validation."""
    errors = _validate_metadata_value({"key": "value"})
    assert len(errors) == 0


def test_validate_metadata_value_empty_dict() -> None:
    """Test that empty dict is valid."""
    errors = _validate_metadata_value({})
    assert len(errors) == 0


def test_validate_metadata_value_not_dict() -> None:
    """Test that non-dict is rejected."""
    errors = _validate_metadata_value("not a dict")
    assert len(errors) > 0
    assert "must be a dictionary" in errors[0].lower()


def test_validate_metadata_value_list() -> None:
    """Test that list is rejected."""
    errors = _validate_metadata_value(["item1", "item2"])
    assert len(errors) > 0
    assert "must be a dictionary" in errors[0].lower()


# --- Integration Tests for New Validators ---


def test_validate_metadata_with_valid_license() -> None:
    """Test validate_metadata with valid license field."""
    metadata = {
        "name": "test-skill",
        "description": "Valid description",
        "license": "MIT",
    }
    errors = validate_metadata(metadata)
    assert len(errors) == 0


def test_validate_metadata_with_custom_license() -> None:
    """Test validate_metadata with custom license string."""
    metadata = {
        "name": "test-skill",
        "description": "Valid description",
        "license": "CustomLicense",
    }
    errors = validate_metadata(metadata)
    assert len(errors) == 0


def test_validate_metadata_with_valid_allowed_tools() -> None:
    """Test validate_metadata with valid allowed-tools field."""
    metadata = {
        "name": "test-skill",
        "description": "Valid description",
        "allowed-tools": ["bash", "python"],
    }
    errors = validate_metadata(metadata)
    assert len(errors) == 0


def test_validate_metadata_with_invalid_allowed_tools() -> None:
    """Test validate_metadata with invalid allowed-tools field."""
    metadata = {
        "name": "test-skill",
        "description": "Valid description",
        "allowed-tools": "not-a-list",
    }
    errors = validate_metadata(metadata)
    assert len(errors) > 0
    assert any("must be a list" in e.lower() for e in errors)


def test_validate_metadata_with_valid_metadata_field() -> None:
    """Test validate_metadata with valid metadata field."""
    metadata = {
        "name": "test-skill",
        "description": "Valid description",
        "metadata": {"version": "1.0.0", "author": "test"},
    }
    errors = validate_metadata(metadata)
    assert len(errors) == 0


def test_validate_metadata_with_invalid_metadata_field() -> None:
    """Test validate_metadata with invalid metadata field."""
    metadata = {
        "name": "test-skill",
        "description": "Valid description",
        "metadata": "not-a-dict",
    }
    errors = validate_metadata(metadata)
    assert len(errors) > 0
    assert any("must be a dictionary" in e.lower() for e in errors)
