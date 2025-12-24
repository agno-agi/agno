import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill, compute_content_hash
from agno.utils.log import log_debug, log_warning


class LocalSkills(SkillLoader):
    """Loads skills from the local filesystem.

    This loader can handle both:
    1. A single skill folder (contains SKILL.md)
    2. A directory containing multiple skill folders

    Args:
        path: Path to a skill folder or directory containing skill folders.
    """

    def __init__(self, path: str):
        self.path = Path(path).resolve()

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
        """
        skill_md_path = folder / "SKILL.md"

        try:
            content = skill_md_path.read_text(encoding="utf-8")
            frontmatter, instructions = self._parse_skill_md(content)

            # Get skill name from frontmatter or folder name
            name = frontmatter.get("name", folder.name)
            description = frontmatter.get("description", "")

            # Get optional fields
            license_info = frontmatter.get("license")
            version = frontmatter.get("version", 1)
            metadata = frontmatter.get("metadata", {})

            # Add source_path and license to metadata for reference
            if metadata is None:
                metadata = {}
            metadata["source_path"] = str(folder)
            if license_info:
                metadata["license"] = license_info

            # Discover scripts
            scripts = self._discover_scripts(folder)

            # Discover references
            references = self._discover_references(folder)

            # Compute content hash for ID
            skill_id = compute_content_hash(name, description, instructions)

            return Skill(
                id=skill_id,
                name=name,
                description=description,
                instructions=instructions,
                scripts=scripts,
                references=references,
                metadata=metadata,
                version=version if isinstance(version, int) else 1,
            )

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

    def _discover_scripts(self, folder: Path) -> List[Dict[str, str]]:
        """Discover script files in the scripts/ subdirectory and load their content.

        Args:
            folder: Path to the skill folder.

        Returns:
            A list of script objects with name and content.
        """
        scripts_dir = folder / "scripts"
        if not scripts_dir.exists() or not scripts_dir.is_dir():
            return []

        scripts: List[Dict[str, str]] = []
        for item in sorted(scripts_dir.iterdir(), key=lambda x: x.name):
            if item.is_file() and not item.name.startswith("."):
                try:
                    content = item.read_text(encoding="utf-8")
                    scripts.append({"name": item.name, "content": content})
                except Exception as e:
                    log_warning(f"Error reading script {item}: {e}")
                    scripts.append({"name": item.name, "content": ""})

        return scripts

    def _discover_references(self, folder: Path) -> List[Dict[str, str]]:
        """Discover reference files in the references/ subdirectory and load their content.

        Args:
            folder: Path to the skill folder.

        Returns:
            A list of reference objects with name and content.
        """
        refs_dir = folder / "references"
        if not refs_dir.exists() or not refs_dir.is_dir():
            return []

        references: List[Dict[str, str]] = []
        for item in sorted(refs_dir.iterdir(), key=lambda x: x.name):
            if item.is_file() and not item.name.startswith("."):
                try:
                    content = item.read_text(encoding="utf-8")
                    references.append({"name": item.name, "content": content})
                except Exception as e:
                    log_warning(f"Error reading reference {item}: {e}")
                    references.append({"name": item.name, "content": ""})

        return references
