"""Unit tests for LocalSkills loader."""

from pathlib import Path

import pytest

from agno.skills.errors import SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.loaders.local import LocalSkills

# --- Initialization Tests ---


def test_local_skills_is_skill_loader() -> None:
    """Test that LocalSkills is a SkillLoader."""
    assert issubclass(LocalSkills, SkillLoader)


def test_local_skills_init_with_string_path(temp_skill_dir: Path) -> None:
    """Test initialization with string path."""
    loader = LocalSkills(str(temp_skill_dir))
    assert loader.path == temp_skill_dir
    assert loader.validate is True


def test_local_skills_init_with_validate_false(temp_skill_dir: Path) -> None:
    """Test initialization with validation disabled."""
    loader = LocalSkills(str(temp_skill_dir), validate=False)
    assert loader.validate is False


def test_local_skills_path_is_resolved(temp_skill_dir: Path) -> None:
    """Test that path is resolved to absolute path."""
    loader = LocalSkills(str(temp_skill_dir))
    assert loader.path.is_absolute()


# --- Single Skill Loading Tests ---


def test_load_single_skill_directory(temp_skill_dir: Path) -> None:
    """Test loading a single skill from its directory."""
    loader = LocalSkills(str(temp_skill_dir))
    skills = loader.load()

    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "test-skill"
    assert skill.description == "A test skill for unit testing"
    assert "Test Skill Instructions" in skill.instructions
    assert skill.source_path == str(temp_skill_dir)


def test_load_skill_with_scripts(temp_skill_dir: Path) -> None:
    """Test that scripts are discovered correctly."""
    loader = LocalSkills(str(temp_skill_dir))
    skills = loader.load()

    assert len(skills) == 1
    skill = skills[0]
    assert "helper.py" in skill.scripts
    assert "runner.sh" in skill.scripts


def test_load_skill_with_references(temp_skill_dir: Path) -> None:
    """Test that references are discovered correctly."""
    loader = LocalSkills(str(temp_skill_dir))
    skills = loader.load()

    assert len(skills) == 1
    skill = skills[0]
    assert "guide.md" in skill.references
    assert "api-docs.md" in skill.references


def test_load_skill_parses_metadata(temp_skill_dir: Path) -> None:
    """Test that metadata from frontmatter is parsed."""
    loader = LocalSkills(str(temp_skill_dir))
    skills = loader.load()

    assert len(skills) == 1
    skill = skills[0]
    assert skill.metadata is not None
    assert skill.metadata["version"] == "1.0.0"
    assert skill.metadata["author"] == "test-author"


def test_load_skill_parses_license(temp_skill_dir: Path) -> None:
    """Test that license from frontmatter is parsed."""
    loader = LocalSkills(str(temp_skill_dir))
    skills = loader.load()

    assert len(skills) == 1
    skill = skills[0]
    assert skill.license == "MIT"


# --- Multiple Skills Loading Tests ---


def test_load_from_parent_directory(temp_skills_dir: Path) -> None:
    """Test loading multiple skills from a parent directory."""
    loader = LocalSkills(str(temp_skills_dir))
    skills = loader.load()

    # Should load 2 skills (code-review and git-workflow)
    # Hidden and non-skill directories should be skipped
    assert len(skills) == 2

    skill_names = {s.name for s in skills}
    assert "code-review" in skill_names
    assert "git-workflow" in skill_names


def test_load_skips_hidden_directories(temp_skills_dir: Path) -> None:
    """Test that hidden directories are skipped."""
    loader = LocalSkills(str(temp_skills_dir))
    skills = loader.load()

    skill_names = {s.name for s in skills}
    assert "hidden-skill" not in skill_names


def test_load_skips_directories_without_skill_md(temp_skills_dir: Path) -> None:
    """Test that directories without SKILL.md are skipped."""
    loader = LocalSkills(str(temp_skills_dir))
    skills = loader.load()

    # "not-a-skill" directory should be skipped
    assert len(skills) == 2


# --- Validation Tests ---


def test_validation_enabled_by_default(temp_skill_dir: Path) -> None:
    """Test that validation is enabled by default."""
    loader = LocalSkills(str(temp_skill_dir))
    assert loader.validate is True


def test_valid_skill_passes_validation(temp_skill_dir: Path) -> None:
    """Test that a valid skill passes validation."""
    loader = LocalSkills(str(temp_skill_dir), validate=True)
    skills = loader.load()
    assert len(skills) == 1


def test_invalid_skill_raises_error_when_validation_enabled(invalid_skill_dir: Path) -> None:
    """Test that invalid skill raises SkillValidationError."""
    loader = LocalSkills(str(invalid_skill_dir), validate=True)

    with pytest.raises(SkillValidationError) as exc_info:
        loader.load()

    # Should contain validation errors
    assert len(exc_info.value.errors) > 0


def test_invalid_skill_with_validation_disabled(invalid_skill_dir: Path) -> None:
    """Test that invalid skill loads when validation is disabled."""
    loader = LocalSkills(str(invalid_skill_dir), validate=False)
    # Should not raise, but the skill may have issues
    skills = loader.load()
    # The skill should still be loaded (with invalid name)
    assert len(skills) == 1


# --- Error Handling Tests ---


def test_path_not_exists_raises_error(tmp_path: Path) -> None:
    """Test that non-existent path raises FileNotFoundError."""
    nonexistent = tmp_path / "does-not-exist"
    loader = LocalSkills(str(nonexistent))

    with pytest.raises(FileNotFoundError) as exc_info:
        loader.load()

    assert "does not exist" in str(exc_info.value).lower()


def test_missing_skill_md_with_validation(tmp_path: Path) -> None:
    """Test that missing SKILL.md with validation raises error."""
    skill_dir = tmp_path / "no-skill-md"
    skill_dir.mkdir()

    loader = LocalSkills(str(skill_dir), validate=True)
    # When pointing directly at a directory that should be a skill,
    # it won't find SKILL.md and should return empty
    skills = loader.load()
    assert len(skills) == 0


# --- Frontmatter Parsing Tests ---


def test_parses_yaml_frontmatter(tmp_path: Path) -> None:
    """Test parsing of YAML frontmatter."""
    skill_dir = tmp_path / "yaml-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: yaml-skill
description: Skill with YAML frontmatter
license: Apache-2.0
metadata:
  version: "2.0.0"
  tags:
    - test
    - yaml
---
# YAML Skill Instructions

Instructions here.
"""
    )

    loader = LocalSkills(str(skill_dir))
    skills = loader.load()

    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "yaml-skill"
    assert skill.license == "Apache-2.0"
    assert skill.metadata["version"] == "2.0.0"
    assert skill.metadata["tags"] == ["test", "yaml"]


def test_instructions_exclude_frontmatter(temp_skill_dir: Path) -> None:
    """Test that instructions don't include frontmatter."""
    loader = LocalSkills(str(temp_skill_dir))
    skills = loader.load()

    skill = skills[0]
    assert "---" not in skill.instructions
    assert "name:" not in skill.instructions


def test_skill_name_from_frontmatter(tmp_path: Path) -> None:
    """Test that skill name comes from frontmatter, not directory name."""
    skill_dir = tmp_path / "directory-name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: directory-name
description: Test skill
---
# Instructions
"""
    )

    loader = LocalSkills(str(skill_dir))
    skills = loader.load()

    assert len(skills) == 1
    assert skills[0].name == "directory-name"


# --- Discovery Tests ---


def test_scripts_sorted_alphabetically(tmp_path: Path) -> None:
    """Test that discovered scripts are sorted alphabetically."""
    skill_dir = tmp_path / "sorted-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: sorted-skill
description: Test sorting
---
# Instructions
"""
    )

    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "z_script.py").write_text("# Z")
    (scripts_dir / "a_script.py").write_text("# A")
    (scripts_dir / "m_script.py").write_text("# M")

    loader = LocalSkills(str(skill_dir))
    skills = loader.load()

    assert skills[0].scripts == ["a_script.py", "m_script.py", "z_script.py"]


def test_references_sorted_alphabetically(tmp_path: Path) -> None:
    """Test that discovered references are sorted alphabetically."""
    skill_dir = tmp_path / "sorted-refs"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: sorted-refs
description: Test reference sorting
---
# Instructions
"""
    )

    refs_dir = skill_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "z_doc.md").write_text("# Z")
    (refs_dir / "a_doc.md").write_text("# A")

    loader = LocalSkills(str(skill_dir))
    skills = loader.load()

    assert skills[0].references == ["a_doc.md", "z_doc.md"]


def test_hidden_files_skipped_in_scripts(tmp_path: Path) -> None:
    """Test that hidden files in scripts/ are skipped."""
    skill_dir = tmp_path / "hidden-scripts"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: hidden-scripts
description: Test hidden file skipping
---
# Instructions
"""
    )

    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "visible.py").write_text("# Visible")
    (scripts_dir / ".hidden.py").write_text("# Hidden")

    loader = LocalSkills(str(skill_dir))
    skills = loader.load()

    assert "visible.py" in skills[0].scripts
    assert ".hidden.py" not in skills[0].scripts


def test_empty_scripts_directory(tmp_path: Path) -> None:
    """Test skill with empty scripts directory."""
    skill_dir = tmp_path / "empty-scripts"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: empty-scripts
description: Test empty scripts
---
# Instructions
"""
    )
    (skill_dir / "scripts").mkdir()

    loader = LocalSkills(str(skill_dir))
    skills = loader.load()

    assert skills[0].scripts == []


def test_no_scripts_directory(tmp_path: Path) -> None:
    """Test skill without scripts directory."""
    skill_dir = tmp_path / "no-scripts"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: no-scripts
description: No scripts directory
---
# Instructions
"""
    )

    loader = LocalSkills(str(skill_dir))
    skills = loader.load()

    assert skills[0].scripts == []


def test_no_references_directory(tmp_path: Path) -> None:
    """Test skill without references directory."""
    skill_dir = tmp_path / "no-refs"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: no-refs
description: No references directory
---
# Instructions
"""
    )

    loader = LocalSkills(str(skill_dir))
    skills = loader.load()

    assert skills[0].references == []
