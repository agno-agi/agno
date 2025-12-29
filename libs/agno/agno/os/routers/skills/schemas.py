"""Pydantic schemas for the skills API router."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SkillFileSchema(BaseModel):
    """Schema for a file (script or reference) attached to a skill."""

    name: str = Field(..., description="Filename (e.g., 'script.py', 'guide.md')")
    content: str = Field(..., description="File content")


class SkillSchema(BaseModel):
    """Schema for a skill in API responses."""

    id: str = Field(..., description="Unique identifier for the skill (content hash)")
    name: str = Field(..., description="Unique skill name")
    description: str = Field(..., description="Short description of what the skill does")
    instructions: str = Field(..., description="Full instructions/guidance for the agent")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata (version, author, tags, etc.)")
    version: int = Field(1, description="Integer version number for the skill")
    scripts: List[SkillFileSchema] = Field(default_factory=list, description="List of scripts with name and content")
    references: List[SkillFileSchema] = Field(
        default_factory=list, description="List of references with name and content"
    )
    created_at: Optional[datetime] = Field(None, description="When the skill was created")
    updated_at: Optional[datetime] = Field(None, description="When the skill was last updated")

    @classmethod
    def from_dict(cls, skill_dict: Dict[str, Any]) -> "SkillSchema":
        """Create a SkillSchema from a dictionary."""
        created_at = skill_dict.get("created_at")
        updated_at = skill_dict.get("updated_at")

        # Handle epoch timestamps
        if isinstance(created_at, (int, float)):
            created_at = datetime.fromtimestamp(created_at, tz=timezone.utc)
        if isinstance(updated_at, (int, float)):
            updated_at = datetime.fromtimestamp(updated_at, tz=timezone.utc)

        # Convert scripts and references to SkillFileSchema objects
        scripts_raw = skill_dict.get("scripts", [])
        references_raw = skill_dict.get("references", [])

        scripts = [
            SkillFileSchema(**s) if isinstance(s, dict) else SkillFileSchema(name=s, content="") for s in scripts_raw
        ]
        references = [
            SkillFileSchema(**r) if isinstance(r, dict) else SkillFileSchema(name=r, content="") for r in references_raw
        ]

        return cls(
            id=skill_dict["id"],
            name=skill_dict["name"],
            description=skill_dict["description"],
            instructions=skill_dict["instructions"],
            metadata=skill_dict.get("metadata"),
            version=skill_dict.get("version", 1),
            scripts=scripts,
            references=references,
            created_at=created_at,
            updated_at=updated_at,
        )


class SkillCreateSchema(BaseModel):
    """Schema for creating a new skill."""

    name: str = Field(..., description="Unique skill name", min_length=1, max_length=255)
    description: str = Field(..., description="Short description of what the skill does", min_length=1)
    instructions: str = Field(..., description="Full instructions/guidance for the agent", min_length=1)
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    version: int = Field(1, description="Integer version number", ge=1)
    scripts: List[SkillFileSchema] = Field(default_factory=list, description="List of scripts with name and content")
    references: List[SkillFileSchema] = Field(
        default_factory=list, description="List of references with name and content"
    )


class SkillUpdateSchema(BaseModel):
    """Schema for updating an existing skill."""

    name: Optional[str] = Field(None, description="Unique skill name", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Short description", min_length=1)
    instructions: Optional[str] = Field(None, description="Full instructions", min_length=1)
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    version: Optional[int] = Field(None, description="Integer version number", ge=1)
    scripts: Optional[List[SkillFileSchema]] = Field(None, description="List of scripts with name and content")
    references: Optional[List[SkillFileSchema]] = Field(None, description="List of references with name and content")


class DeleteSkillsRequest(BaseModel):
    """Schema for bulk skill deletion."""

    skill_ids: List[str] = Field(..., description="List of skill IDs to delete", min_length=1)
