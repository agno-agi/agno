"""Skill-related exceptions."""

from typing import List, Optional


class SkillError(Exception):
    """Base exception for all skill-related errors."""

    pass


class SkillParseError(SkillError):
    """Raised when SKILL.md parsing fails."""

    pass


class SkillValidationError(SkillError):
    """Raised when skill validation fails.

    Attributes:
        errors: List of validation error messages.
    """

    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors if errors is not None else [message]

    def __str__(self) -> str:
        if len(self.errors) == 1:
            return self.errors[0]
        return f"{len(self.errors)} validation errors: {'; '.join(self.errors)}"
