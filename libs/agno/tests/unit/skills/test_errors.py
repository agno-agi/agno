"""Unit tests for skill exceptions."""

import pytest

from agno.skills.errors import SkillError, SkillParseError, SkillValidationError

# --- SkillError Tests ---


def test_skill_error_is_exception() -> None:
    """Test that SkillError is a subclass of Exception."""
    assert issubclass(SkillError, Exception)


def test_skill_error_can_be_raised() -> None:
    """Test that SkillError can be raised and caught."""
    with pytest.raises(SkillError) as exc_info:
        raise SkillError("Test error")
    assert str(exc_info.value) == "Test error"


def test_skill_error_can_be_caught_as_exception() -> None:
    """Test that SkillError can be caught as generic Exception."""
    with pytest.raises(Exception):
        raise SkillError("Test error")


# --- SkillParseError Tests ---


def test_skill_parse_error_is_skill_error() -> None:
    """Test that SkillParseError is a subclass of SkillError."""
    assert issubclass(SkillParseError, SkillError)


def test_skill_parse_error_can_be_raised() -> None:
    """Test that SkillParseError can be raised and caught."""
    with pytest.raises(SkillParseError) as exc_info:
        raise SkillParseError("Failed to parse SKILL.md")
    assert str(exc_info.value) == "Failed to parse SKILL.md"


def test_skill_parse_error_caught_as_skill_error() -> None:
    """Test that SkillParseError can be caught as SkillError."""
    with pytest.raises(SkillError):
        raise SkillParseError("Parse failed")


# --- SkillValidationError Tests ---


def test_skill_validation_error_is_skill_error() -> None:
    """Test that SkillValidationError is a subclass of SkillError."""
    assert issubclass(SkillValidationError, SkillError)


def test_validation_error_with_single_error() -> None:
    """Test SkillValidationError with a single error message."""
    error = SkillValidationError("Single error")
    assert error.errors == ["Single error"]
    assert str(error) == "Single error"


def test_validation_error_with_errors_list() -> None:
    """Test SkillValidationError with explicit errors list."""
    errors = ["Error 1", "Error 2", "Error 3"]
    error = SkillValidationError("Validation failed", errors=errors)
    assert error.errors == errors
    assert "3 validation errors" in str(error)
    assert "Error 1" in str(error)
    assert "Error 2" in str(error)
    assert "Error 3" in str(error)


def test_validation_error_with_empty_errors_list() -> None:
    """Test SkillValidationError with empty errors list."""
    error = SkillValidationError("Validation failed", errors=[])
    assert error.errors == []
    # With empty errors list, __str__ returns "0 validation errors: "
    assert "0 validation errors" in str(error)


def test_validation_error_str_single_item_list() -> None:
    """Test __str__ with single item in errors list."""
    error = SkillValidationError("Wrapper message", errors=["Only one error"])
    assert str(error) == "Only one error"


def test_validation_error_str_multiple_items() -> None:
    """Test __str__ with multiple items in errors list."""
    error = SkillValidationError("Wrapper", errors=["Error A", "Error B"])
    result = str(error)
    assert "2 validation errors" in result
    assert "Error A" in result
    assert "Error B" in result


def test_validation_error_can_be_raised_and_caught() -> None:
    """Test that SkillValidationError can be raised and caught."""
    with pytest.raises(SkillValidationError) as exc_info:
        raise SkillValidationError("Validation failed", errors=["Name invalid", "Description missing"])
    assert len(exc_info.value.errors) == 2
    assert "Name invalid" in exc_info.value.errors


def test_validation_error_caught_as_skill_error() -> None:
    """Test that SkillValidationError can be caught as SkillError."""
    with pytest.raises(SkillError):
        raise SkillValidationError("Validation failed")


def test_validation_error_errors_attribute_accessible() -> None:
    """Test that errors attribute is accessible on caught exception."""
    try:
        raise SkillValidationError("Failed", errors=["Error 1", "Error 2"])
    except SkillValidationError as e:
        assert hasattr(e, "errors")
        assert isinstance(e.errors, list)
        assert len(e.errors) == 2
