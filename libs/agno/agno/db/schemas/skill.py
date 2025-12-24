from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


@dataclass
class Skill:
    """Model for Skills stored in database.

    A skill provides structured instructions, reference documentation,
    and optional scripts that an agent can access to perform specific tasks.

    Attributes:
        id: SHA256 content hash used as primary key
        name: Unique skill name
        description: Short description of what the skill does
        instructions: Full SKILL.md body (the instructions/guidance for the agent)
        metadata: Optional metadata (version, author, tags, etc.)
        version: Integer version number for the skill
        scripts: List of script objects with name and content
        references: List of reference objects with name and content
        created_at: Epoch timestamp when skill was created
        updated_at: Epoch timestamp when skill was last updated
    """

    id: str
    name: str
    description: str
    instructions: str
    metadata: Optional[Dict[str, Any]] = None
    version: int = 1
    scripts: List[Dict[str, str]] = field(default_factory=list)  # [{"name": "...", "content": "..."}]
    references: List[Dict[str, str]] = field(default_factory=list)  # [{"name": "...", "content": "..."}]
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        """Automatically set/normalize created_at and updated_at."""
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the Skill to a dictionary representation."""
        created_at = datetime.fromtimestamp(self.created_at).isoformat() if self.created_at is not None else None
        updated_at = datetime.fromtimestamp(self.updated_at).isoformat() if self.updated_at is not None else created_at
        _dict = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "metadata": self.metadata,
            "version": self.version,
            "scripts": self.scripts,
            "references": self.references,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        """Create a Skill from a dictionary."""
        data = dict(data)

        # Preserve 0 and None explicitly; only process if key exists
        if "created_at" in data and data["created_at"] is not None:
            data["created_at"] = to_epoch_s(data["created_at"])
        if "updated_at" in data and data["updated_at"] is not None:
            data["updated_at"] = to_epoch_s(data["updated_at"])

        # Ensure scripts and references are lists
        if "scripts" not in data or data["scripts"] is None:
            data["scripts"] = []
        if "references" not in data or data["references"] is None:
            data["references"] = []

        return cls(**data)
