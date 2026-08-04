from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.skills.errors import SkillValidationError
from agno.skills.skill import Skill
from agno.skills.utils import read_file_safe
from agno.utils.dttm import now_epoch_s, to_epoch_s
from agno.utils.path_safety import safe_join_relative_path


@dataclass
class SkillRow:
    """Model for a row of the skills table.

    Named SkillRow, not Skill: agno.skills.skill.Skill owns that name for the in-memory
    content object this row serializes. `scripts` and `references` hold
    {filename: UTF-8 text}; the filename lists the in-memory Skill declares are the keys.
    """

    id: str
    name: str
    description: str
    instructions: str
    # Ownership, not identity: None means a shared/global skill, and name alone
    # stays the unique key. Lives on the row only -- Skill has no user_id field.
    user_id: Optional[str] = None
    source_type: str = "local"
    scripts: Dict[str, str] = field(default_factory=dict)
    references: Dict[str, str] = field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = None
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    version: int = 1
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values (important for DB updates)."""
        return {
            "id": self.id,
            "name": self.name,
            "user_id": self.user_id,
            "description": self.description,
            "source_type": self.source_type,
            "instructions": self.instructions,
            "scripts": self.scripts,
            "references": self.references,
            "metadata": self.metadata,
            "license": self.license,
            "compatibility": self.compatibility,
            "allowed_tools": self.allowed_tools,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillRow":
        data = dict(data)
        valid_keys = {
            "id",
            "name",
            "user_id",
            "description",
            "source_type",
            "instructions",
            "scripts",
            "references",
            "metadata",
            "license",
            "compatibility",
            "allowed_tools",
            "version",
            "created_at",
            "updated_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    def to_skill(self) -> Skill:
        """Build the content-carrying Skill this row stores.

        The content dicts pass through verbatim: {} is a valid content-carrying shape
        (a skill with no files) and must not collapse to None, or Skill.__post_init__
        rejects the result as neither path-backed nor content-carrying.

        Raises SkillValidationError if any content entry is not str -> str: Skill's own
        validation checks structure only, and non-string content would otherwise persist
        and fail later at script materialization.
        """
        errors = [
            f"{field_name} entry {filename!r} must map a string filename to string content"
            for field_name, contents in (("scripts", self.scripts), ("references", self.references))
            for filename, text in contents.items()
            if not isinstance(filename, str) or not isinstance(text, str)
        ]
        if errors:
            raise SkillValidationError(f"Skill '{self.name}' has non-string content", errors=errors)
        return Skill(
            name=self.name,
            description=self.description,
            instructions=self.instructions,
            scripts=list(self.scripts.keys()),
            references=list(self.references.keys()),
            metadata=self.metadata,
            license=self.license,
            compatibility=self.compatibility,
            allowed_tools=self.allowed_tools,
            # Always "db": everything built here is content-carrying and served from the
            # table, which is the distinction source_type exists to make. Passing the
            # column through instead reported "local" for a skill created through the API,
            # so the field stopped meaning anything past the first hop. The row keeps its
            # own value as a record of where the skill was authored.
            source_type="db",
            reference_contents=dict(self.references),
            script_contents=dict(self.scripts),
        )

    @classmethod
    def from_skill(
        cls, skill: Skill, id: Optional[str] = None, version: int = 1, user_id: Optional[str] = None
    ) -> "SkillRow":
        """Build a row from a Skill.

        A path-backed skill has its declared files read from disk, so the row always
        carries full content. A content-carrying skill's dicts pass through verbatim.
        user_id is row-level ownership supplied by the caller; Skill does not carry it.
        """
        if skill.source_path is not None:
            root = Path(skill.source_path)
            scripts = {
                filename: read_file_safe(safe_join_relative_path(root / "scripts", filename))
                for filename in skill.scripts
            }
            references = {
                filename: read_file_safe(safe_join_relative_path(root / "references", filename))
                for filename in skill.references
            }
        else:
            scripts = dict(skill.script_contents or {})
            references = dict(skill.reference_contents or {})
        return cls(
            id=id or str(uuid4()),
            name=skill.name,
            user_id=user_id,
            description=skill.description,
            instructions=skill.instructions,
            source_type=skill.source_type,
            scripts=scripts,
            references=references,
            metadata=skill.metadata,
            license=skill.license,
            compatibility=skill.compatibility,
            allowed_tools=skill.allowed_tools,
            version=version,
        )
