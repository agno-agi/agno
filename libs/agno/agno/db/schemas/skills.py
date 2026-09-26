from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


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
    # Optimistic concurrency, not the skill's own version: server-managed, starts at 1 and
    # bumps on every successful write, never set by a caller. A semantic version a user
    # keeps -- typically under `metadata` -- is opaque to the system and unrelated to this.
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

    def content_errors(self) -> List[str]:
        """List what stops this row's content from becoming a Skill; empty means valid.

        Non-string content would otherwise persist and only fail later, when the skill's
        files are written to disk. Pure data check: turning the row into a Skill lives in
        the loader (agno.skills.loaders.db), so this module never imports the SDK layer.
        """
        return [
            f"{field_name} entry {filename!r} must map a string filename to string content"
            for field_name, contents in (("scripts", self.scripts), ("references", self.references))
            for filename, text in contents.items()
            if not isinstance(filename, str) or not isinstance(text, str)
        ]
