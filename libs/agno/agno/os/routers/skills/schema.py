from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SkillSummaryResponse(BaseModel):
    """A skill as returned by the list endpoint: metadata only, no content."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique identifier for the skill")
    name: str = Field(..., description="Unique skill name, the resolution key")
    user_id: Optional[str] = Field(None, description="Owning user ID; null means a shared skill")
    description: str = Field(..., description="What the skill does")
    source_type: str = Field(..., description="Where the skill came from (e.g. 'local', 'url', 'db')")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    license: Optional[str] = Field(None, description="License identifier")
    compatibility: Optional[str] = Field(None, description="Compatibility notes")
    allowed_tools: Optional[List[str]] = Field(None, description="Tool names the skill is allowed to use")
    version: int = Field(..., description="Server-managed version, bumped on every successful update")
    created_at: Optional[int] = Field(None, description="Creation timestamp (Unix epoch seconds)")
    updated_at: Optional[int] = Field(None, description="Last update timestamp (Unix epoch seconds)")


class SkillResponse(SkillSummaryResponse):
    """A single skill as returned by the detail endpoint: the summary plus full content."""

    instructions: str = Field(..., description="The skill's instructions (the SKILL.md body)")
    scripts: Dict[str, str] = Field(default_factory=dict, description="Script content, filename -> UTF-8 text")
    references: Dict[str, str] = Field(default_factory=dict, description="Reference content, filename -> UTF-8 text")


class SkillCreate(BaseModel):
    """Request body for creating a skill. id and version are server-managed."""

    name: str = Field(..., description="Unique skill name")
    description: str = Field(..., description="What the skill does")
    instructions: str = Field(..., description="The skill's instructions (the SKILL.md body)")
    scripts: Dict[str, str] = Field(default_factory=dict, description="Script content, filename -> UTF-8 text")
    references: Dict[str, str] = Field(default_factory=dict, description="Reference content, filename -> UTF-8 text")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    license: Optional[str] = Field(None, description="License identifier")
    compatibility: Optional[str] = Field(None, description="Compatibility notes")
    allowed_tools: Optional[List[str]] = Field(None, description="Tool names the skill is allowed to use")
    source_type: str = Field("local", description="Where the skill came from (e.g. 'local', 'url', 'db')")
    user_id: Optional[str] = Field(
        None,
        description=(
            "Owning user ID. Omit or null for a shared skill. When user isolation is "
            "enabled, must match the authenticated caller or be omitted/null."
        ),
    )


class SkillUpdate(BaseModel):
    """Request body for updating a skill. The name is the immutable resolution key
    (it is the path parameter, not an editable field), and so is user_id: ownership is
    set at create and never moves, so it is absent here rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(..., description="The version being edited; a mismatch returns 409 with the current version")
    description: Optional[str] = Field(None, description="What the skill does")
    instructions: Optional[str] = Field(None, description="The skill's instructions (the SKILL.md body)")
    scripts: Optional[Dict[str, str]] = Field(None, description="Script content, filename -> UTF-8 text")
    references: Optional[Dict[str, str]] = Field(None, description="Reference content, filename -> UTF-8 text")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    license: Optional[str] = Field(None, description="License identifier")
    compatibility: Optional[str] = Field(None, description="Compatibility notes")
    allowed_tools: Optional[List[str]] = Field(None, description="Tool names the skill is allowed to use")
    source_type: Optional[str] = Field(None, description="Where the skill came from (e.g. 'local', 'url', 'db')")
