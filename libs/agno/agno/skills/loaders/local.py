import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agno.skills.errors import SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.skills.validator import validate_skill_directory
from agno.utils.log import log_debug, log_warning


class LocalSkills(SkillLoader):
    """Loads skills from the local filesystem.

    This loader can handle both:
    1. A single skill folder (contains SKILL.md)
    2. A directory containing multiple skill folders

    Args:
        path: Path to a skill folder or directory containing skill folders.
        validate: Whether to validate skills against the Agent Skills spec.
            If True (default), invalid skills will raise SkillValidationError.
    """

    def __init__(self, path: str, validate: bool = True):
        self.path = Path(path).resolve()
        self.validate = validate

    def load(self) -> List[Skill]:
        """Load skills from the local filesystem.

        Returns:
            A list of Skill objects loaded from the filesystem.

        Raises:
            FileNotFoundError: If the path doesn't exist.
        """
        if not self.path.exists():
            raise FileNotFoundError(f"Skills path does not exist: {self.path}")

        skills: List[Skill] = []

        # Check if this is a single skill folder or a directory of skills
        skill_md_path = self.path / "SKILL.md"
        if skill_md_path.exists():
            # Single skill folder
            skill = self._load_skill_from_folder(self.path)
            if skill:
                skills.append(skill)
        else:
            # Directory of skill folders
            for item in self.path.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    skill_md = item / "SKILL.md"
                    if skill_md.exists():
                        skill = self._load_skill_from_folder(item)
                        if skill:
                            skills.append(skill)
                    else:
                        log_debug(f"Skipping directory without SKILL.md: {item}")

        log_debug(f"Loaded {len(skills)} skills from {self.path}")
        return skills

    def _load_skill_from_folder(self, folder: Path) -> Optional[Skill]:
        """Load a single skill from a folder.

        Args:
            folder: Path to the skill folder.

        Returns:
            A Skill object if successful, None if there's an error.

        Raises:
            SkillValidationError: If validation is enabled and the skill is invalid.
        """
        # Validate skill directory structure and content if validation is enabled
        if self.validate:
            errors = validate_skill_directory(folder)
            if errors:
                raise SkillValidationError(
                    f"Skill validation failed for '{folder.name}'",
                    errors=errors,
                )

        skill_md_path = folder / "SKILL.md"

        try:
            content = skill_md_path.read_text(encoding="utf-8")
            frontmatter, instructions = self._parse_skill_md(content)

            # Get skill name from the frontmatter or folder name
            name = frontmatter.get("name", folder.name)
            description = frontmatter.get("description", "")

            # Get optional fields
            license_info = frontmatter.get("license")
            metadata = frontmatter.get("metadata")
            compatibility = frontmatter.get("compatibility")
            allowed_tools = frontmatter.get("allowed-tools")

            # Discover scripts
            scripts = self._discover_scripts(folder)

            # Discover references
            references = self._discover_references(folder)

            return Skill(
                name=name,
                description=description,
                instructions=instructions,
                source_path=str(folder),
                scripts=scripts,
                references=references,
                metadata=metadata,
                license=license_info,
                compatibility=compatibility,
                allowed_tools=allowed_tools,
            )

        except SkillValidationError:
            raise  # Re-raise validation errors
        except Exception as e:
            log_warning(f"Error loading skill from {folder}: {e}")
            return None

    def _parse_skill_md(self, content: str) -> Tuple[Dict[str, Any], str]:
        """Parse SKILL.md content into frontmatter and instructions.

        Args:
            content: The raw SKILL.md content.

        Returns:
            A tuple of (frontmatter_dict, instructions_body).
        """
        frontmatter: Dict[str, Any] = {}
        instructions = content

        # Check for YAML frontmatter (between --- delimiters)
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)

        if frontmatter_match:
            frontmatter_text = frontmatter_match.group(1)
            instructions = frontmatter_match.group(2).strip()

            # Parse YAML frontmatter
            try:
                import yaml

                frontmatter = yaml.safe_load(frontmatter_text) or {}
            except ImportError:
                # Fallback: simple key-value parsing if yaml not available
                frontmatter = self._parse_simple_frontmatter(frontmatter_text)
            except Exception as e:
                log_warning(f"Error parsing YAML frontmatter: {e}")
                frontmatter = self._parse_simple_frontmatter(frontmatter_text)

        return frontmatter, instructions

    def _parse_simple_frontmatter(self, text: str) -> Dict[str, Any]:
        """Simple fallback frontmatter parser for basic key: value pairs.

        Args:
            text: The frontmatter text.

        Returns:
            A dictionary of parsed key-value pairs.
        """
        result: Dict[str, Any] = {}
        for line in text.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                result[key] = value
        return result

    def _discover_scripts(self, folder: Path) -> List[str]:
        """Discover script files in the scripts/ subdirectory.

        Args:
            folder: Path to the skill folder.

        Returns:
            A list of script filenames.
        """
        scripts_dir = folder / "scripts"
        if not scripts_dir.exists() or not scripts_dir.is_dir():
            return []

        scripts: List[str] = []
        for item in scripts_dir.iterdir():
            if item.is_file() and not item.name.startswith("."):
                scripts.append(item.name)

        return sorted(scripts)

    def _discover_references(self, folder: Path) -> List[str]:
        """Discover reference files in the references/ subdirectory.

        Args:
            folder: Path to the skill folder.

        Returns:
            A list of reference filenames.
        """
        refs_dir = folder / "references"
        if not refs_dir.exists() or not refs_dir.is_dir():
            return []

        references: List[str] = []
        for item in refs_dir.iterdir():
            if item.is_file() and not item.name.startswith("."):
                references.append(item.name)

        return sorted(references)
