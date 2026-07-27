from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.skills.errors import SkillValidationError


@dataclass
class Skill:
    """Represents a skill that an agent can use.

    A skill provides structured instructions, reference documentation,
    and optional scripts that an agent can access to perform specific tasks.

    A skill is exactly one of two shapes. Path-backed: `source_path` points at a skill folder
    on disk, and the content dicts are unset. Content-carrying: `source_path` is unset, and
    every filename in `scripts` and `references` has an entry in the matching content dict.
    Any other combination raises SkillValidationError.

    Attributes:
        name: Unique skill name (from folder name or SKILL.md frontmatter)
        description: Short description of what the skill does
        instructions: Full SKILL.md body (the instructions/guidance for the agent)
        source_path: Filesystem path to the skill folder (path-backed skills only)
        scripts: List of script filenames in scripts/ subdirectory
        references: List of reference filenames in references/ subdirectory
        metadata: Optional metadata from frontmatter (version, author, tags, etc.)
        license: Optional license information
        compatibility: Optional compatibility requirements
        allowed_tools: Optional list of tools this skill is allowed to use
        source_type: Where the skill came from: "local", "url" or "db"
        reference_contents: Reference filename to UTF-8 text (content-carrying skills only)
        script_contents: Script filename to UTF-8 text (content-carrying skills only)
    """

    name: str
    description: str
    instructions: str
    source_path: Optional[str] = None
    scripts: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    # Appended rather than grouped with source_path/scripts/references so that every pre-existing
    # field keeps the positional slot it had before these three were added.
    source_type: str = "local"
    reference_contents: Optional[Dict[str, str]] = None
    script_contents: Optional[Dict[str, str]] = None

    def __post_init__(self) -> None:
        # `None` versus `{}` is the discriminator, not emptiness: a skill with instructions and
        # no files is content-carrying with two empty dicts, and must not be read as path-backed.
        has_contents = self.reference_contents is not None or self.script_contents is not None
        if self.source_path is not None and has_contents:
            raise SkillValidationError(
                f"Skill '{self.name}' sets both source_path and inline contents: it must be one or the other"
            )
        if self.source_path is None and not has_contents:
            raise SkillValidationError(f"Skill '{self.name}' sets neither source_path nor inline contents")
        if self.source_path is not None:
            return

        errors = [
            f"Script '{script}' has no entry in script_contents"
            for script in self.scripts
            if script not in (self.script_contents or {})
        ]
        errors += [
            f"Reference '{reference}' has no entry in reference_contents"
            for reference in self.references
            if reference not in (self.reference_contents or {})
        ]
        if errors:
            raise SkillValidationError(f"Skill '{self.name}' is missing content for declared files", errors=errors)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the Skill to a dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "source_path": self.source_path,
            "scripts": self.scripts,
            "references": self.references,
            "metadata": self.metadata,
            "license": self.license,
            "compatibility": self.compatibility,
            "allowed_tools": self.allowed_tools,
            "source_type": self.source_type,
            "reference_contents": self.reference_contents,
            "script_contents": self.script_contents,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        """Create a Skill from a dictionary."""
        return cls(
            name=data["name"],
            description=data["description"],
            instructions=data["instructions"],
            source_path=data.get("source_path"),
            scripts=data.get("scripts", []),
            references=data.get("references", []),
            metadata=data.get("metadata"),
            license=data.get("license"),
            compatibility=data.get("compatibility"),
            allowed_tools=data.get("allowed_tools"),
            source_type=data.get("source_type", "local"),
            reference_contents=data.get("reference_contents"),
            script_contents=data.get("script_contents"),
        )
