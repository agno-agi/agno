from typing import Dict, List, Optional, Sequence, Union

from agno.db.base import BaseDb
from agno.skills.component import SkillRef, resolve_skill_version
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.utils.log import log_warning


class DbSkills(SkillLoader):
    """Loads skills stored as components in the database.

    Each reference names a stored skill and which version to use: an exact version,
    ``"latest"``, or None for the current published version (pinned when the agent
    or team is saved). A plain string is shorthand for ``SkillRef(id)``.

    Args:
        db: The database the skills are stored in.
        skills: The skills to load.
        user_id: When set, only skills this user may see are loaded: their own,
            unowned ones, and published ones.
    """

    def __init__(self, db: BaseDb, skills: Sequence[Union[str, SkillRef]], user_id: Optional[str] = None):
        if not isinstance(db, BaseDb):
            raise ValueError("DbSkills needs a sync database; async databases do not support components yet")
        self.db = db
        self.refs: List[SkillRef] = [SkillRef(ref) if isinstance(ref, str) else ref for ref in skills]
        ids = [ref.id for ref in self.refs]
        duplicates = sorted({skill_id for skill_id in ids if ids.count(skill_id) > 1})
        if duplicates:
            raise ValueError(f"DbSkills references these skills more than once: {duplicates}")
        self.user_id = user_id
        # Filled by load(): the version each reference resolved to, and the references that resolved to nothing.
        self.resolved_versions: Dict[str, int] = {}
        self.missing: List[SkillRef] = []
        self.loaded = False

    def load(self, *, user_id: Optional[str] = None) -> List[Skill]:
        skills: List[Skill] = []
        resolved_versions: Dict[str, int] = {}
        missing: List[SkillRef] = []
        for ref in self.refs:
            pinned = ref.version if isinstance(ref.version, int) else None
            resolved = resolve_skill_version(
                ref.id, db=self.db, version=pinned, user_id=self.user_id, published_only=True
            )
            if resolved is None:
                wanted = f"version {pinned}" if pinned is not None else "a published version"
                log_warning(f"Skill '{ref.id}' has no {wanted}; skipping it")
                missing.append(ref)
                continue
            skill, version = resolved
            skills.append(skill)
            resolved_versions[ref.id] = version
        self.resolved_versions = resolved_versions
        self.missing = missing
        self.loaded = True
        return skills

    def __repr__(self) -> str:
        return f"DbSkills(skills={[ref.id for ref in self.refs]!r})"
