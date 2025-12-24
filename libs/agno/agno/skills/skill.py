"""Skill model and utility functions.

This module re-exports the Skill dataclass from db/schemas/skill.py
and provides utility functions for skill management.
"""

import hashlib
from typing import Optional

from agno.db.schemas.skill import Skill

__all__ = ["Skill", "compute_content_hash"]


def compute_content_hash(name: str, description: str, instructions: str) -> str:
    """Compute a content hash for a skill.

    This creates a SHA256 hash of the skill's core content
    (name, description, instructions) to use as a unique identifier.

    Args:
        name: The skill name.
        description: The skill description.
        instructions: The skill instructions.

    Returns:
        A SHA256 hex digest of the combined content.
    """
    content = f"{name}|{description}|{instructions}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def create_skill(
    name: str,
    description: str,
    instructions: str,
    scripts: Optional[list] = None,
    references: Optional[list] = None,
    metadata: Optional[dict] = None,
    version: int = 1,
    skill_id: Optional[str] = None,
) -> Skill:
    """Create a new Skill instance with auto-generated ID.

    Args:
        name: Unique skill name.
        description: Short description of what the skill does.
        instructions: Full instructions/guidance for the agent.
        scripts: List of script filenames.
        references: List of reference filenames.
        metadata: Optional metadata (version, author, tags, etc.).
        version: Integer version number.
        skill_id: Optional explicit ID. If not provided, generates from content hash.

    Returns:
        A new Skill instance.
    """
    if skill_id is None:
        skill_id = compute_content_hash(name, description, instructions)

    return Skill(
        id=skill_id,
        name=name,
        description=description,
        instructions=instructions,
        metadata=metadata,
        version=version,
        scripts=scripts or [],
        references=references or [],
    )
