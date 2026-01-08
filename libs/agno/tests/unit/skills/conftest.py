"""Pytest fixtures for skills testing."""

from pathlib import Path
from typing import List

import pytest

from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill


@pytest.fixture
def sample_skill() -> Skill:
    """Create a sample Skill object with all fields populated."""
    return Skill(
        name="test-skill",
        description="A test skill for unit testing",
        instructions="# Test Skill\n\nFollow these instructions to complete the task.",
        source_path="/path/to/test-skill",
        scripts=["helper.py", "runner.sh"],
        references=["guide.md", "api-docs.md"],
        metadata={"version": "1.0.0", "author": "test-author", "tags": ["test", "example"]},
        license="MIT",
    )


@pytest.fixture
def minimal_skill() -> Skill:
    """Create a minimal Skill with only required fields."""
    return Skill(
        name="minimal-skill",
        description="A minimal skill",
        instructions="Minimal instructions",
        source_path="/path/to/minimal-skill",
    )


@pytest.fixture
def sample_skill_dict() -> dict:
    """Create a sample skill dictionary for testing from_dict."""
    return {
        "name": "dict-skill",
        "description": "A skill from dictionary",
        "instructions": "Instructions from dict",
        "source_path": "/path/to/dict-skill",
        "scripts": ["script.py"],
        "references": ["ref.md"],
        "metadata": {"version": "2.0.0"},
        "license": "Apache-2.0",
    }


@pytest.fixture
def temp_skill_dir(tmp_path: Path) -> Path:
    """Create a valid temporary skill directory."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()

    # Create SKILL.md with valid frontmatter
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: test-skill
description: A test skill for unit testing
license: MIT
metadata:
  version: "1.0.0"
  author: test-author
---
# Test Skill Instructions

Follow these instructions to complete the task.

## Steps

1. First step
2. Second step
"""
    )

    # Create scripts directory with a sample script
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "helper.py").write_text("# Helper script\nprint('Hello from helper')")
    (scripts_dir / "runner.sh").write_text("#!/bin/bash\necho 'Running'")

    # Create references directory with sample docs
    refs_dir = skill_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "guide.md").write_text("# Guide\n\nThis is a reference guide.")
    (refs_dir / "api-docs.md").write_text("# API Documentation\n\nAPI details here.")

    return skill_dir


@pytest.fixture
def temp_skills_dir(tmp_path: Path) -> Path:
    """Create a directory containing multiple skill directories."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create first skill
    skill1 = skills_dir / "code-review"
    skill1.mkdir()
    (skill1 / "SKILL.md").write_text(
        """---
name: code-review
description: Code review assistance
---
# Code Review Instructions

Review code for quality and correctness.
"""
    )

    # Create second skill
    skill2 = skills_dir / "git-workflow"
    skill2.mkdir()
    (skill2 / "SKILL.md").write_text(
        """---
name: git-workflow
description: Git workflow guidance
---
# Git Workflow Instructions

Follow standard git workflow practices.
"""
    )

    # Create a hidden directory (should be skipped)
    hidden = skills_dir / ".hidden-skill"
    hidden.mkdir()
    (hidden / "SKILL.md").write_text(
        """---
name: hidden-skill
description: Should be skipped
---
Hidden skill
"""
    )

    # Create a directory without SKILL.md (should be skipped)
    no_skill = skills_dir / "not-a-skill"
    no_skill.mkdir()
    (no_skill / "README.md").write_text("This is not a skill directory")

    return skills_dir


@pytest.fixture
def invalid_skill_dir(tmp_path: Path) -> Path:
    """Create an invalid skill directory for error testing."""
    skill_dir = tmp_path / "invalid-skill"
    skill_dir.mkdir()

    # Create SKILL.md with invalid frontmatter
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: Invalid_Skill
description:
unknown_field: should not be here
---
# Invalid Skill

This skill has validation errors.
"""
    )

    return skill_dir


@pytest.fixture
def skill_dir_missing_frontmatter(tmp_path: Path) -> Path:
    """Create a skill directory with missing frontmatter delimiters."""
    skill_dir = tmp_path / "bad-frontmatter"
    skill_dir.mkdir()

    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """name: bad-frontmatter
description: Missing frontmatter delimiters
---
# Bad Skill

Missing opening delimiter.
"""
    )

    return skill_dir


class MockSkillLoader(SkillLoader):
    """Mock skill loader for testing."""

    def __init__(self, skills: List[Skill]):
        self._skills = skills

    def load(self) -> List[Skill]:
        return self._skills


@pytest.fixture
def mock_loader(sample_skill: Skill) -> MockSkillLoader:
    """Create a mock loader that returns a single skill."""
    return MockSkillLoader([sample_skill])


@pytest.fixture
def mock_loader_multiple(sample_skill: Skill, minimal_skill: Skill) -> MockSkillLoader:
    """Create a mock loader that returns multiple skills."""
    return MockSkillLoader([sample_skill, minimal_skill])


@pytest.fixture
def mock_loader_empty() -> MockSkillLoader:
    """Create a mock loader that returns no skills."""
    return MockSkillLoader([])
