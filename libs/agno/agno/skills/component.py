"""Skills stored as versioned components in the database."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from agno.db.base import BaseDb, ComponentType
from agno.skills.errors import SkillValidationError
from agno.skills.skill import Skill
from agno.skills.validator import validate_metadata
from agno.utils.path_safety import safe_join_relative_path

# Total UTF-8 size of a stored skill: instructions plus every script and reference.
MAX_SKILL_CONTENT_BYTES = 1024 * 1024

SKILL_LINK_KIND = "skill"

SkillSelector = Optional[Union[int, Literal["latest"]]]


@dataclass
class SkillRef:
    """A reference from an agent or team to a stored skill.

    ``version`` is an exact version, ``"latest"`` to follow the current published
    version, or None to use the current published version and pin it when the
    agent or team is saved.
    """

    id: str
    version: SkillSelector = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("`id` must be a non-empty string")
        if self.version is not None and self.version != "latest":
            # bool is an int subclass; True would otherwise pass as version 1.
            if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
                raise ValueError("`version` must be a positive integer, 'latest', or None")

    def to_dict(self) -> Dict[str, Any]:
        reference: Dict[str, Any] = {"skill_id": self.id}
        if self.version is not None:
            reference["version"] = self.version
        return reference

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillRef":
        return cls(id=data.get("skill_id", ""), version=data.get("version"))


def _read_skill_files(skill: Skill, subdir: str, filenames: List[str]) -> Dict[str, str]:
    if skill.source_path is None:
        raise SkillValidationError(f"Skill '{skill.name}' has no source_path to read files from")
    base = Path(skill.source_path) / subdir
    return {filename: safe_join_relative_path(base, filename).read_text(encoding="utf-8") for filename in filenames}


def skill_to_config(skill: Skill) -> Dict[str, Any]:
    """The stored component config for a skill: its metadata and the full text of every file.

    A path-backed skill has its files read from disk, so the stored version does not
    depend on the host that saved it.

    Raises:
        SkillValidationError: If the metadata is invalid or the content exceeds MAX_SKILL_CONTENT_BYTES.
    """
    metadata: Dict[str, Any] = {"name": skill.name, "description": skill.description}
    if skill.license is not None:
        metadata["license"] = skill.license
    if skill.compatibility is not None:
        metadata["compatibility"] = skill.compatibility
    if skill.allowed_tools is not None:
        metadata["allowed-tools"] = skill.allowed_tools
    if skill.metadata is not None:
        metadata["metadata"] = skill.metadata
    errors = validate_metadata(metadata)
    if errors:
        raise SkillValidationError(f"Skill '{skill.name}' cannot be saved", errors=errors)

    if skill.source_path is not None:
        scripts = _read_skill_files(skill, "scripts", skill.scripts)
        references = _read_skill_files(skill, "references", skill.references)
    else:
        scripts = dict(skill.script_contents or {})
        references = dict(skill.reference_contents or {})

    size = len(skill.instructions.encode("utf-8"))
    size += sum(len(text.encode("utf-8")) for text in [*scripts.values(), *references.values()])
    if size > MAX_SKILL_CONTENT_BYTES:
        raise SkillValidationError(
            f"Skill '{skill.name}' is {size} bytes; a stored skill holds at most {MAX_SKILL_CONTENT_BYTES} bytes"
        )

    config: Dict[str, Any] = {
        "type": ComponentType.SKILL.value,
        "name": skill.name,
        "description": skill.description,
        "instructions": skill.instructions,
        "scripts": scripts,
        "references": references,
    }
    for key in ("license", "compatibility", "allowed_tools", "metadata"):
        value = getattr(skill, key)
        if value is not None:
            config[key] = value
    return config


def skill_from_config(config: Dict[str, Any], skill_id: str) -> Skill:
    """Rebuild a content-carrying skill from its stored component config."""
    component_type = config.get("type")
    if component_type is not None and component_type != ComponentType.SKILL.value:
        raise ValueError(f"Expected a skill config, got type {component_type!r}")
    scripts = dict(config.get("scripts") or {})
    references = dict(config.get("references") or {})
    return Skill(
        name=config["name"],
        description=config["description"],
        instructions=config["instructions"],
        scripts=sorted(scripts),
        references=sorted(references),
        metadata=config.get("metadata"),
        license=config.get("license"),
        compatibility=config.get("compatibility"),
        allowed_tools=config.get("allowed_tools"),
        source_type="db",
        script_contents=scripts,
        reference_contents=references,
        id=skill_id,
    )


def _require_sync_db(db: Any, action: str) -> None:
    if not isinstance(db, BaseDb):
        raise ValueError(f"Async databases not yet supported for {action}(). Use a sync database.")


def save_skill(skill: Skill, *, db: BaseDb, user_id: Optional[str] = None) -> int:
    """Append a new published version of a skill and move its current pointer to it."""
    _require_sync_db(db, "save")
    config = skill_to_config(skill)
    skill_id = skill.id or skill.name
    db.upsert_component(
        component_id=skill_id,
        component_type=ComponentType.SKILL,
        name=skill.name,
        description=skill.description,
        user_id=user_id,
    )
    row = db.upsert_config(component_id=skill_id, config=config, stage="published")
    skill.id = skill_id
    return row["version"]


def load_skill(
    skill_id: str,
    *,
    db: BaseDb,
    version: Optional[int] = None,
    label: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Skill]:
    """Load a stored skill: the current published version, or an exact version or label."""
    resolved = resolve_skill_version(skill_id, db=db, version=version, label=label, user_id=user_id)
    return resolved[0] if resolved is not None else None


def resolve_skill_version(
    skill_id: str,
    *,
    db: BaseDb,
    version: Optional[int] = None,
    label: Optional[str] = None,
    user_id: Optional[str] = None,
    published_only: bool = False,
) -> Optional[Tuple[Skill, int]]:
    """The skill and the version it was read from, or None when there is nothing to read.

    Without a version or label this reads the current published version and never a draft.
    """
    # Configs are untyped; the catalog row is what says this id is a skill.
    if db.get_component(component_id=skill_id, component_type=ComponentType.SKILL, user_id=user_id) is None:
        return None
    if version is None and label is None:
        row = db.get_current_config(component_id=skill_id)
    else:
        row = db.get_config(component_id=skill_id, version=version, label=label)
        if row is not None and published_only and row.get("stage") != "published":
            return None
    if row is None or row.get("config") is None:
        return None
    return skill_from_config(row["config"], skill_id), row["version"]


def skill_links_for_save(
    skills_config: Optional[Dict[str, Any]], *, db: BaseDb, label: str, user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Validate every skill reference against the catalog and build its link rows.

    Runs before the first write of the agent or team. A pinned reference must name a
    published version; ``"latest"`` stores a NULL version; a reference with no version
    links the current published version.

    Raises:
        ValueError: If a reference names no skill, or a version that is not published.
    """
    links: List[Dict[str, Any]] = []
    for position, data in enumerate((skills_config or {}).get("refs") or []):
        ref = SkillRef.from_dict(data)
        component = db.get_component(component_id=ref.id, component_type=ComponentType.SKILL, user_id=user_id)
        if component is None:
            raise ValueError(f"{label} references skill '{ref.id}', which is not a stored skill. Save it first.")
        current_version = component.get("current_version")
        target = ref.version if isinstance(ref.version, int) else current_version
        row = db.get_config(component_id=ref.id, version=target) if target is not None else None
        if row is None or row.get("stage") != "published":
            wanted = f"version {target}" if target is not None else "a published version"
            raise ValueError(f"{label} references skill '{ref.id}' {wanted}, which is not published")
        links.append(
            {
                "link_kind": SKILL_LINK_KIND,
                "link_key": ref.id,
                "child_component_id": ref.id,
                "child_version": None if ref.version == "latest" else target,
                "position": position,
            }
        )
    return links


def pin_skill_refs(skills_config: Optional[Dict[str, Any]], links: List[Dict[str, Any]]) -> None:
    """Write each link's pinned version into the matching unversioned reference, in place."""
    pins = {link["child_component_id"]: link["child_version"] for link in links}
    for ref in (skills_config or {}).get("refs") or []:
        if ref.get("version") is None and pins.get(ref.get("skill_id")) is not None:
            ref["version"] = pins[ref["skill_id"]]


def delete_skill(skill_id: str, *, db: BaseDb, hard_delete: bool = False) -> bool:
    """Delete a stored skill. Refuses while a saved agent or team references it."""
    _require_sync_db(db, "delete")
    # Only a row the catalog types as a skill may be deleted here.
    if db.get_component(component_id=skill_id, component_type=ComponentType.SKILL, include_deleted=hard_delete) is None:
        return False
    return db.delete_component(component_id=skill_id, hard_delete=hard_delete, require_no_dependents=True)
