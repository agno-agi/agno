"""Skill validation logic following the Agent Skills spec."""

import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

# Constants per Agent Skills Spec
MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500

# Allowed frontmatter fields per Agent Skills Spec
ALLOWED_FIELDS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}


def _validate_name(name: str, skill_dir: Optional[Path] = None) -> List[str]:
    """Validate skill name format and directory match.

    Skill names support alphanumeric characters plus hyphens.
    Names must be lowercase and cannot start/end with hyphens.

    Args:
        name: The skill name to validate.
        skill_dir: Optional path to skill directory (for name-directory match check).

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    if not name or not isinstance(name, str) or not name.strip():
        errors.append("Field 'name' must be a non-empty string")
        return errors

    name = unicodedata.normalize("NFKC", name.strip())

    if len(name) > MAX_SKILL_NAME_LENGTH:
        errors.append(f"Skill name '{name}' exceeds {MAX_SKILL_NAME_LENGTH} character limit ({len(name)} chars)")

    if name != name.lower():
        errors.append(f"Skill name '{name}' must be lowercase")

    if name.startswith("-") or name.endswith("-"):
        errors.append("Skill name cannot start or end with a hyphen")

    if "--" in name:
        errors.append("Skill name cannot contain consecutive hyphens")

    if not all(c.isalnum() or c == "-" for c in name):
        errors.append(
            f"Skill name '{name}' contains invalid characters. Only letters, digits, and hyphens are allowed."
        )

    if skill_dir:
        dir_name = unicodedata.normalize("NFKC", skill_dir.name)
        if dir_name != name:
            errors.append(f"Directory name '{dir_name}' must match skill name '{name}'")

    return errors


def _validate_description(description: str) -> List[str]:
    """Validate description format.

    Args:
        description: The skill description to validate.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    if not description or not isinstance(description, str) or not description.strip():
        errors.append("Field 'description' must be a non-empty string")
        return errors

    if len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(f"Description exceeds {MAX_DESCRIPTION_LENGTH} character limit ({len(description)} chars)")

    return errors


def _validate_compatibility(compatibility: str) -> List[str]:
    """Validate compatibility format.

    Args:
        compatibility: The compatibility string to validate.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    if not isinstance(compatibility, str):
        errors.append("Field 'compatibility' must be a string")
        return errors

    if len(compatibility) > MAX_COMPATIBILITY_LENGTH:
        errors.append(f"Compatibility exceeds {MAX_COMPATIBILITY_LENGTH} character limit ({len(compatibility)} chars)")

    return errors


def _validate_license(license_val: str) -> List[str]:
    """Validate license field.

    Args:
        license_val: The license string to validate.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors: List[str] = []

    if not isinstance(license_val, str):
        errors.append("Field 'license' must be a string")

    return errors


def _validate_allowed_tools(allowed_tools) -> List[str]:
    """Validate allowed-tools field.

    Args:
        allowed_tools: The allowed-tools value to validate.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    if not isinstance(allowed_tools, list):
        errors.append("Field 'allowed-tools' must be a list")
        return errors

    if not all(isinstance(tool, str) for tool in allowed_tools):
        errors.append("Field 'allowed-tools' must be a list of strings")

    return errors


def _validate_metadata_value(metadata_val) -> List[str]:
    """Validate metadata field value.

    Args:
        metadata_val: The metadata value to validate.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    if not isinstance(metadata_val, dict):
        errors.append("Field 'metadata' must be a dictionary")

    return errors


def _validate_metadata_fields(metadata: Dict) -> List[str]:
    """Validate that only allowed fields are present in frontmatter.

    Args:
        metadata: Parsed frontmatter dictionary.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []

    extra_fields = set(metadata.keys()) - ALLOWED_FIELDS
    if extra_fields:
        errors.append(
            f"Unexpected fields in frontmatter: {', '.join(sorted(extra_fields))}. "
            f"Only {sorted(ALLOWED_FIELDS)} are allowed."
        )

    return errors


def validate_metadata(metadata: Dict, skill_dir: Optional[Path] = None) -> List[str]:
    """Validate parsed skill metadata.

    This is the core validation function that works on already-parsed metadata.

    Args:
        metadata: Parsed YAML frontmatter dictionary.
        skill_dir: Optional path to skill directory (for name-directory match check).

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors = []
    errors.extend(_validate_metadata_fields(metadata))

    if "name" not in metadata:
        errors.append("Missing required field in frontmatter: name")
    else:
        errors.extend(_validate_name(metadata["name"], skill_dir))

    if "description" not in metadata:
        errors.append("Missing required field in frontmatter: description")
    else:
        errors.extend(_validate_description(metadata["description"]))

    if "compatibility" in metadata:
        errors.extend(_validate_compatibility(metadata["compatibility"]))

    if "license" in metadata:
        errors.extend(_validate_license(metadata["license"]))

    if "allowed-tools" in metadata:
        errors.extend(_validate_allowed_tools(metadata["allowed-tools"]))

    if "metadata" in metadata:
        errors.extend(_validate_metadata_value(metadata["metadata"]))

    return errors


def validate_skill_directory(skill_dir: Path) -> List[str]:
    """Validate a skill directory structure and contents.

    Args:
        skill_dir: Path to the skill directory.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    import yaml

    from agno.skills.errors import SkillParseError

    skill_dir = Path(skill_dir)

    if not skill_dir.exists():
        return [f"Path does not exist: {skill_dir}"]

    if not skill_dir.is_dir():
        return [f"Not a directory: {skill_dir}"]

    # Find SKILL.md file (only uppercase supported)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return ["Missing required file: SKILL.md"]

    # Parse frontmatter
    try:
        content = skill_md.read_text(encoding="utf-8")

        if not content.startswith("---"):
            raise SkillParseError("SKILL.md must start with YAML frontmatter (---)")

        parts = content.split("---", 2)
        if len(parts) < 3:
            raise SkillParseError("SKILL.md frontmatter not properly closed with ---")

        frontmatter_str = parts[1]
        metadata = yaml.safe_load(frontmatter_str)

        if not isinstance(metadata, dict):
            raise SkillParseError("SKILL.md frontmatter must be a YAML mapping")

    except SkillParseError as e:
        return [str(e)]
    except yaml.YAMLError as e:
        return [f"Invalid YAML in frontmatter: {e}"]
    except Exception as e:
        return [f"Error reading SKILL.md: {e}"]

    return validate_metadata(metadata, skill_dir)
